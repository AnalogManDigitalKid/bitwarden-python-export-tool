#!/usr/bin/env python3
"""
Back up one or more Bitwarden vaults with the Bitwarden CLI (bw).

For each vault in bitwarden-config.toml it logs in with the personal API key,
unlocks with the master password, and exports the personal vault and/or
organizations (plain JSON, password-protected JSON, attachments) into:

    <output_dir>/<yyyy-MM-dd_HHmm>/<vault name>/

Secrets are passed to bw through environment variables rather than command-line
arguments where bw allows it, so they don't show up in the process list.

Needs Python 3.11+ (for tomllib) and the Bitwarden CLI.
Usage:  py bitwarden_backup.py [--config path\\to\\bitwarden-config.toml]
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ---------------------------------------------------------------- logging ---

class Log:
    def __init__(self, path):
        self.f = open(path, "a", encoding="utf-8")

    def __call__(self, msg=""):
        print(msg, flush=True)
        self.f.write(msg + "\n")
        self.f.flush()


log = None


def safe_name(s):
    s = BAD_CHARS.sub("_", s or "").strip().rstrip(". ")
    return s[:100] or "_"


# ----------------------------------------------------------------- bw CLI ---

class BwError(Exception):
    pass


class Bw:
    def __init__(self, exe, data_dir):
        self.exe = exe
        self.base_env = dict(os.environ, BITWARDENCLI_APPDATA_DIR=data_dir)
        self.session = None

    def run(self, *args, env=None, check=True):
        full_env = dict(self.base_env)
        if self.session:
            full_env["BW_SESSION"] = self.session
        full_env.update(env or {})
        proc = subprocess.run([self.exe, *args, "--nointeraction"], env=full_env,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")
        if check and proc.returncode != 0:
            msg = (proc.stderr or proc.stdout).strip() or f"exit code {proc.returncode}"
            raise BwError(f"bw {args[0]} {args[1] if len(args) > 1 and not args[1].startswith('-') else ''}"
                          .strip() + f" failed: {msg}")
        return proc.stdout.strip()

    def logout(self):
        self.run("logout", check=False)
        self.session = None


# ------------------------------------------------------------ config load ---

def load_config(path):
    if not os.path.exists(path):
        sys.exit(f"Config not found: {path}\n"
                 "Copy bitwarden-config.example.toml to bitwarden-config.toml and fill it in.")
    try:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        sys.exit(f"Config file has a syntax error: {e}")
    vaults = cfg.get("vault") or []
    if not vaults:
        sys.exit(f"No [[vault]] sections in {path}")
    names = set()
    for i, v in enumerate(vaults, 1):
        for key in ("name", "client_id", "client_secret", "master_password"):
            if not v.get(key):
                sys.exit(f"Vault #{i} is missing '{key}' in {path}")
        if v["name"].lower() in names:
            sys.exit(f"Duplicate vault name '{v['name']}' in {path}")
        names.add(v["name"].lower())
        for e in v.get("export") or []:
            if e.get("type") not in ("personal", "organization"):
                sys.exit(f"Vault '{v['name']}': export type must be 'personal' or 'organization'")
            if e["type"] == "organization" and not e.get("organization_id"):
                sys.exit(f"Vault '{v['name']}': organization export needs organization_id")
            if e.get("encrypted") and not e.get("encryption_password"):
                sys.exit(f"Vault '{v['name']}': encrypted export needs encryption_password")
    return cfg


def resolve(path):
    return path if os.path.isabs(path) else os.path.join(HERE, path)


# ---------------------------------------------------------------- exports ---

def size_str(att):
    """bw reports attachment size in bytes as a string; show it human-readable."""
    try:
        n = float(att.get("size") or "")
    except ValueError:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f" ({n:.0f} {unit})" if unit == "B" else f" ({n:.1f} {unit})"
        n /= 1024


def export_attachments(bw, items, dest):
    items = [i for i in items if i.get("attachments")]
    if not items:
        log("    no attachments")
        return
    total = sum(len(i["attachments"]) for i in items)
    used, count = set(), 0
    for item in items:
        folder = safe_name(item.get("name") or item["id"])
        if folder.lower() in used:  # two items with the same name
            folder = safe_name(f"{item.get('name')} ({item['id'][:8]})")
        used.add(folder.lower())
        item_dir = os.path.join(dest, folder)
        os.makedirs(item_dir, exist_ok=True)

        seen = set()
        for att in item["attachments"]:
            fname = safe_name(att.get("fileName") or att["id"])
            if fname.lower() in seen:  # same filename twice on one item
                stem, ext = os.path.splitext(fname)
                fname = f"{stem} ({att['id'][:8]}){ext}"
            seen.add(fname.lower())
            count += 1
            log(f"    [{count}/{total}] {folder}/{fname}{size_str(att)}")
            bw.run("get", "attachment", att["id"], "--itemid", item["id"],
                   "--output", os.path.join(item_dir, fname))
    log(f"    {count} attachments from {len(items)} items")


def export_vault_file(bw, vault_dir, base, exp, org_id=None):
    org_args = ["--organizationid", org_id] if org_id else []
    if exp.get("unencrypted"):
        bw.run("export", "--format", "json", "--output",
               os.path.join(vault_dir, base + ".json"), *org_args)
        log(f"    {base}.json")
    if exp.get("encrypted"):
        # bw only accepts the export password as an argument
        bw.run("export", "--format", "encrypted_json", "--password", exp["encryption_password"],
               "--output", os.path.join(vault_dir, base + "_encrypted.json"), *org_args)
        log(f"    {base}_encrypted.json (password protected)")


def backup_vault(bw, vault, run_dir):
    bw.logout()
    bw.run("login", "--apikey", env={"BW_CLIENTID": vault["client_id"],
                                     "BW_CLIENTSECRET": vault["client_secret"]})
    bw.session = bw.run("unlock", "--passwordenv", "BW_PASSWORD", "--raw",
                        env={"BW_PASSWORD": vault["master_password"]})
    if not bw.session:
        raise BwError("unlock returned no session")
    bw.run("sync")

    vault_dir = os.path.join(run_dir, safe_name(vault["name"]))
    os.makedirs(vault_dir, exist_ok=True)

    all_items = json.loads(bw.run("list", "items") or "[]")
    orgs = {o["id"]: o.get("name") or o["id"]
            for o in json.loads(bw.run("list", "organizations") or "[]")}

    for exp in vault.get("export") or []:
        if exp["type"] == "personal":
            items = [i for i in all_items if not i.get("organizationId")]
            log(f"  personal vault: {len(items)} items")
            if not items:
                log("    empty, skipping")
                continue
            export_vault_file(bw, vault_dir, "personal", exp)
            if exp.get("attachments"):
                export_attachments(bw, items, os.path.join(vault_dir, "attachments", "personal"))

        else:
            org_id = exp["organization_id"]
            if org_id not in orgs:
                raise BwError(f"this account is not a member of organization {org_id}")
            org_name = safe_name(orgs[org_id])
            items = [i for i in all_items if i.get("organizationId") == org_id]
            log(f"  organization '{orgs[org_id]}': {len(items)} items")
            export_vault_file(bw, vault_dir, f"organization_{org_name}", exp, org_id)
            if exp.get("attachments"):
                export_attachments(bw, items,
                                   os.path.join(vault_dir, "attachments", f"organization_{org_name}"))


# ------------------------------------------------------------------- main ---

def main():
    global log
    ap = argparse.ArgumentParser(description="Back up Bitwarden vaults with the bw CLI")
    ap.add_argument("--config", default=os.path.join(HERE, "bitwarden-config.toml"))
    ap.add_argument("--no-update-check", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    out_root = resolve(cfg.get("output_dir", "exports"))
    run_dir = os.path.join(out_root, stamp)
    log_dir = resolve(cfg.get("log_dir", "logs"))
    data_dir = resolve(cfg.get("cli_data_dir", "bw-cli-data"))
    os.makedirs(log_dir, exist_ok=True)
    log = Log(os.path.join(log_dir, f"bitwarden-backup-{stamp}.log"))

    exe = cfg.get("bw_path") or shutil.which("bw")
    if not exe or not os.path.exists(exe):
        sys.exit("Bitwarden CLI not found. Install it (winget install Bitwarden.CLI) "
                 "or set bw_path in the config.")
    bw = Bw(exe, data_dir)

    log(f"Bitwarden backup, run {stamp}")
    log(f"bw {bw.run('--version', check=False)} at {exe}")

    if cfg.get("server"):
        bw.logout()
        bw.run("config", "server", cfg["server"])
    log(f"Server: {bw.run('config', 'server', check=False) or '(unknown)'}")

    if not args.no_update_check:
        update = bw.run("update", check=False)
        if update and "no update" not in update.lower():
            log(update)
            if input("A bw update may be available. Continue anyway? [y/N] ").strip().lower() != "y":
                sys.exit("Aborted.")

    failed = []
    for vault in cfg["vault"]:
        log(f"\n== {vault['name']} ==")
        try:
            backup_vault(bw, vault, run_dir)
            log(f"  {vault['name']}: done")
        except (BwError, json.JSONDecodeError, OSError) as e:
            log(f"  ERROR: {e}")
            failed.append(vault["name"])
        finally:
            bw.logout()

    shutil.rmtree(data_dir, ignore_errors=True)  # remove the CLI's cached login/vault data

    if failed:
        log(f"\nFinished with errors in: {', '.join(failed)}")
        sys.exit(1)
    log(f"\nAll vaults exported to: {run_dir}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nInterrupted.")
