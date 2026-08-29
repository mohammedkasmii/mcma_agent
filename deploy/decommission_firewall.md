# Firewall decommission runbook — MCMA Dashboard (Port 8000)

INC-00 permanently removed the dashboard's LAN exposure: the API now binds to
`127.0.0.1` only and no tracked script creates a firewall rule any more. The
`profile=any` inbound rule that `Autoriser_Reseau_Local.bat` used to create
may still exist on hosts where it was previously run, and must be removed by
an administrator.

## Administrator commands (run in an elevated prompt — do NOT run from automation)

Delete the rule:

```bat
netsh advfirewall firewall delete rule name="MCMA Dashboard (Port 8000)"
```

Verify the deletion:

```bat
netsh advfirewall firewall show rule name="MCMA Dashboard (Port 8000)"
```

Expected verification result: Windows reports that **no rules match** the
specified criteria.

## Scope note

Repository containment (this commit) and host decommission (the commands
above) are separate steps. Do **not** claim the host rule was removed without
owner-executed evidence of the two commands above on each affected machine.
