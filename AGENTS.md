# Repository Agent Instructions

## GitHub CLI

The GitHub CLI reads the user's macOS keyring only outside the normal sandbox in
this workspace. Run `gh` commands with escalated sandbox permissions from the
first attempt instead of probing in the default sandbox first.

This applies to commands such as:

- `gh auth status`
- `gh pr create`
- `gh pr view`
- `gh pr merge`

Do not ask the user to re-authenticate unless the escalated `gh auth status`
command also reports an invalid or missing token.
