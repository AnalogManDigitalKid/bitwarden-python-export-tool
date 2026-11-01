# Bitwarden Vault Backup

Scripted Bitwarden vault backups using the official CLI: personal and organization exports, encrypted JSON and attachments, for multiple accounts.

> [!CAUTION]
> **Keep this entire folder inside encrypted storage, such as a [VeraCrypt](https://veracrypt.io/) container.**
>
> The config file holds your **master passwords and API keys in plain text**, and the unencrypted exports contain **every password, note and attachment in your vault** in readable form. Anyone who can read this folder can read your vault.
>
> - Mount the container, run the backup, then dismount it.
> - Never put the config or exports on unencrypted disks, cloud sync folders (OneDrive, Dropbox, Google Drive) or in git.
> - Use a strong, unique password for the container itself, and store it somewhere other than the vault you're backing up (or you can't get to your backup when you need it most).

## Features

- Backs up **multiple Bitwarden accounts** in one run
- Exports the **personal vault** and/or **organizations**
- **Plain JSON** and **password-protected JSON** exports (the latter can be imported into any Bitwarden account)
- Downloads **file attachments**, organized by item
- Each run goes into its own **dated folder**, with a **log file** per run
- One failing vault doesn't stop the others; a summary at the end lists any failures
- Master password, client secret and session key are passed to `bw` through **environment variables**, not command-line arguments, so they don't appear in the process list
- The CLI's working data is kept inside the folder and **deleted after every run**
- All paths are relative to the script, so the container's **drive letter doesn't matter**

## Requirements

- [Python 3.11+](https://www.python.org/downloads/) (standard library only, nothing to `pip install`)
- [Bitwarden CLI](https://bitwarden.com/help/cli/) (`bw`)

On Windows:

```powershell
winget install Python.Python.3.12
winget install Bitwarden.CLI
```

## Setup

1. Create and mount an encrypted container (see the caution above).
2. Copy these files into it:
   ```
   bitwarden_backup.py
   run-bitwarden-backup.bat
   bitwarden-config.example.toml
   ```
3. Copy `bitwarden-config.example.toml` to `bitwarden-config.toml`.
4. Get your personal API key for each account: Bitwarden web vault > **Settings > Security > Keys > View API key**.
5. Fill in `bitwarden-config.toml`. Each option is explained in the file.

### Config overview

```toml
output_dir = 'exports'

[[vault]]
name            = 'Personal'
client_id       = 'user.xxxxxxxx-...'
client_secret   = '...'
master_password = '...'

  [[vault.export]]
  type                = 'personal'      # or 'organization' (+ organization_id)
  unencrypted         = true
  encrypted           = true
  encryption_password = '...'
  attachments         = true
```

Use `'single quotes'` for passwords so they're read exactly as typed. Add another `[[vault]]` block for each extra account.

## Usage

**Windows:** double-click `run-bitwarden-backup.bat`.

**Any OS:**

```bash
python3 bitwarden_backup.py
python3 bitwarden_backup.py --config path/to/other-config.toml
python3 bitwarden_backup.py --no-update-check
```

If `bw update` reports a newer version, the script asks before continuing.

## Output

```
exports/
└── 2026-11-01_1744/
    └── Personal/
        ├── personal.json
        ├── personal_encrypted.json
        ├── organization_Family.json
        ├── organization_Family_encrypted.json
        └── attachments/
            ├── personal/
            │   └── <item name>/<file>
            └── organization_Family/
                └── <item name>/<file>
logs/
└── bitwarden-backup-2026-11-01_1744.log
```

| File | What it is |
| --- | --- |
| `*.json` | Plain export. Readable by anyone with the file. |
| `*_encrypted.json` | Password-protected export. Import into any Bitwarden account with the `encryption_password`. |
| `attachments/` | Attachments are not included in Bitwarden exports, so they're downloaded separately. |

## Restoring

- **Encrypted export:** Bitwarden web vault > **Tools > Import data** > format **Bitwarden (json)** > enter the export password.
- **Plain export:** same steps, no password.
- **Attachments:** re-attach manually to the restored items.

Test a restore now and then (for example, into a throwaway account) so you know the backups actually work.

## API key notes

- The personal API key **does not expire**. The `client_id` never changes; the `client_secret` only changes if you rotate it.
- **Rotating** the key (Settings > Security > Keys > Rotate API Key) invalidates the old secret. Update the config right away.
- The API key only logs in. The **master password** is still needed to decrypt the vault, so the API key can't be used on its own.

## Security notes

- The `encrypted` export password is the one secret passed as a command-line argument, because `bw export` only accepts it that way.
- `bw-cli-data/` holds the CLI's login state and cached (encrypted) vault while the script runs. It's deleted at the end of every run.
- The `.gitignore` excludes `bitwarden-config.toml`, `exports/`, `logs/` and `bw-cli-data/`. Only the `.example` config belongs in git.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `Config not found` | Copy `bitwarden-config.example.toml` to `bitwarden-config.toml`. |
| `Bitwarden CLI not found` | Install it, or set `bw_path` in the config. |
| `bw login failed` | Check `client_id` / `client_secret`, or the key may have been rotated. |
| `bw unlock failed` | Check `master_password` (and that the password in the file has no stray quotes). |
| `not a member of organization` | Check `organization_id` with `bw list organizations`. |
| Wrong server / account not found | Set `server` in the config for the EU cloud or a self-hosted instance. |
