# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .ai_knowledge_service import (
    chunk_text,
    extract_text_from_binary,
    extract_text_from_url,
)

_logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 20


class AiKnowledgeDocument(models.Model):
    _name = "ai.knowledge.document"
    _description = "Otomater AI - Knowledge Base Document"
    _order = "id desc"

    name = fields.Char(required=True)
    source_type = fields.Selection(
        [("note", "Internal Note"), ("file", "File Upload"), ("url", "Website URL")],
        default="note",
        required=True,
    )
    file = fields.Binary(string="File", attachment=True)
    file_name = fields.Char()
    url = fields.Char(string="Website URL")
    content_text = fields.Text(
        string="Content",
        help="For Internal Notes, type/paste the text directly here. For "
        "File/URL sources, this is filled in automatically by Process.",
    )
    category = fields.Char(help="Free-text category/tag, e.g. HR Policy, Product FAQ.")
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company
    )
    active = fields.Boolean(default=True)
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("processing", "Processing"),
            ("indexed", "Indexed"),
            ("error", "Error"),
        ],
        default="draft",
        required=True,
    )
    error_message = fields.Text(readonly=True)
    chunk_ids = fields.One2many("ai.knowledge.chunk", "document_id")
    chunk_count = fields.Integer(compute="_compute_chunk_count", store=True)
    last_indexed = fields.Datetime(readonly=True)

    @api.depends("chunk_ids")
    def _compute_chunk_count(self):
        for doc in self:
            doc.chunk_count = len(doc.chunk_ids)

    def action_process(self):
        """Extract text (file/url sources), chunk it, embed every chunk
        with the configured embedding provider, and (re)store the result.
        Safe to re-run - existing chunks are replaced each time."""
        for doc in self:
            try:
                doc.status = "processing"
                text = doc._extract_text()
                if not text or not text.strip():
                    raise UserError(_("No text could be extracted from this source."))

                provider = self.env["ai.provider"].get_default_embedding_provider(
                    doc.company_id.id
                )
                if not provider:
                    raise UserError(_(
                        "No embedding provider is configured. Go to Otomater AI > "
                        "AI Settings > Providers and mark one provider (OpenAI, "
                        "Azure OpenAI, Gemini, or Ollama) as 'Use for Embeddings'."
                    ))

                pieces = chunk_text(text)
                if not pieces:
                    raise UserError(_("This document produced no usable text chunks."))

                doc.chunk_ids.unlink()
                vectors = []
                for i in range(0, len(pieces), EMBEDDING_BATCH_SIZE):
                    batch = pieces[i:i + EMBEDDING_BATCH_SIZE]
                    vectors.extend(provider.get_embedding(batch))

                chunk_vals = [
                    {
                        "document_id": doc.id,
                        "sequence": idx,
                        "content": piece,
                        "embedding": json.dumps(vector),
                    }
                    for idx, (piece, vector) in enumerate(zip(pieces, vectors))
                ]
                self.env["ai.knowledge.chunk"].create(chunk_vals)

                doc.write(
                    {
                        "content_text": text if doc.source_type != "note" else doc.content_text,
                        "status": "indexed",
                        "error_message": False,
                        "last_indexed": fields.Datetime.now(),
                    }
                )
            except UserError as exc:
                doc.write({"status": "error", "error_message": str(exc)})
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Otomater AI knowledge processing failed for %s", doc.name)
                doc.write({"status": "error", "error_message": "Unexpected error: %s" % exc})
        return True

    def _extract_text(self):
        self.ensure_one()
        if self.source_type == "note":
            return self.content_text or ""
        if self.source_type == "file":
            if not self.file:
                raise UserError(_("No file uploaded."))
            import base64

            return extract_text_from_binary(self.file_name, base64.b64decode(self.file))
        if self.source_type == "url":
            if not self.url:
                raise UserError(_("No URL set."))
            return extract_text_from_url(self.url)
        return ""
