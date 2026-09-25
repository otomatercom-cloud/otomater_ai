# -*- coding: utf-8 -*-
from odoo import fields, models


class AiKnowledgeChunk(models.Model):
    _name = "ai.knowledge.chunk"
    _description = "Otomater AI - Knowledge Base Chunk"
    _order = "document_id, sequence"

    document_id = fields.Many2one(
        "ai.knowledge.document", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    content = fields.Text(required=True)
    embedding = fields.Text(help="JSON-encoded embedding vector.")
