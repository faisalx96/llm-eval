# qym docs portal

This folder is the authoring source for the self-hosted qym developer portal.

- `docs/` contains generated and curated content pages.
- `static/openapi.json` contains the generated OpenAPI artifact.
- `package.json` and Docusaurus config define the docs-only build.

Run the generator before building:

```bash
python -m tools.docs
```

