# One-click deploy bundle for Render

## What this is
This folder is a GitHub-ready parser app for your Custom GPT.

## Fastest path
1. Create a new empty GitHub repo.
2. Upload every file in this folder to the repo root.
3. In Render, click **New +** -> **Blueprint**.
4. Connect the GitHub repo.
5. Render will detect `render.yaml` and deploy automatically.
6. When deployment finishes, copy your public Render URL.
7. Open `openapi.json` and replace:
   `https://REPLACE-WITH-YOUR-RENDER-URL.onrender.com`
   with your real Render URL.
8. In your GPT, go to **Configure** -> **Actions** -> **Import from OpenAPI** and upload the updated `openapi.json`.
9. Paste `gpt-instructions.txt` into the GPT's Instructions field.
10. Add `conversation-starter.txt` as a conversation starter.

## Example Render URL
`https://combined-noted-from-lead-parser.onrender.com`

## Important note
This parser is deterministic and more reliable than prompt-only parsing, but I have only tuned it against the sample layout discussed in this chat. If your Zoho exports vary, the parser may need one more tuning pass.
