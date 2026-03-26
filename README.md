# Combined Noted from Lead Parser Bundle v3

Upload **all files in this folder** to the root of your GitHub repo and replace the older files.

## Important fixes in v3
- The API now returns only `rows`.
- It no longer returns a raw `fields` object that the GPT can accidentally display.
- `openapi.json` already points to:
  https://combined-noted-from-lead-parser.onrender.com

## Files
- `app.py`
- `requirements.txt`
- `render.yaml`
- `openapi.json`
- `gpt-instructions.txt`
- `conversation-starter.txt`
- `README.md`

## After upload
1. Commit the files to GitHub.
2. Let Render redeploy.
3. In your GPT, remove the old Action and re-import the new `openapi.json`.
4. Replace the GPT Instructions with `gpt-instructions.txt`.
5. Keep the conversation starter from `conversation-starter.txt`.
