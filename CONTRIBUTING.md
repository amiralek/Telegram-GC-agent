# Contributing

Use Python 3.11 or newer and a virtual environment. Install development
dependencies and run the offline regression suite:

```console
python -m pip install -e ".[ai]"
python -m unittest discover -s tests -v
python -m pip check
```

Raw-only work can instead install `-e .` and run
`python -m unittest discover -s tests -p test_raw_exports.py -v` and
`python -m unittest discover -s tests -p test_onboarding.py -v`.
Tests use fabricated messages and mocked APIs. Never add live credentials,
session files, private group names/history, member spreadsheets or personal
research outputs as fixtures. Use `.env.example` for configuration examples.

Keep raw exports complete, chronological and attributed. Telegram access must
remain read-only, rate limited and subject to the account's actual permissions.
Preserve old CLI/MCP interfaces where possible. Changes affecting analysis must
keep that feature optional. Cover changed behavior with focused offline tests.

Open a pull request explaining the user-visible change and relevant validation.
MIT licensing applies to contributions. See SECURITY.md for private reporting.
