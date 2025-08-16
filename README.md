# Validator (Simple Bundle)

Minimal JSON Schema validation setup (Draft 2020-12) with **no dynamic patching**.

## Files
- `validate.py` — command-line validator
- `schema.json` — strict schema
- `sample.yaml` — sample instance
- `test_validate.py` — pytest smoke test

## Validate
```bash
python3 validate.py --schema schema.json --data sample.yaml
```

## Run tests
```bash
pytest -q
```
