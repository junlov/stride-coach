"""Regenerate the public client contract, without tokens or a database."""

import json
from pathlib import Path

from stride_coach.api import ServerConfig, create_app

schema = create_app(
    ServerConfig(
        token="schema-generation-placeholder-only",
        database_url="postgresql://schema:synthetic-schema-password@localhost/schema",
    )
).openapi()
Path("docs/openapi.json").write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
