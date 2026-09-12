#!/usr/bin/env python3
"""r08_smtp_probe.py — mail domain DNS(MX/A/SPF) + port25 banner probe (runner side).
Usage: python3 r08_smtp_probe.py domain1 domain2 ...   (needs dnspython)"""
import json, socket, sys
import dns.resolver

out = []
for d in sys.argv[1:]:
    r = {"domain": d}
    hosts = []
    try:
        ans = sorted(dns.resolver.resolve(d, "MX"), key=lambda x: x.preference)
        hosts = [str(x.exchange).rstrip(".") for x in ans]
        r["mx"] = hosts[:3]
    except Exception as e:
        r["mx_error"] = (type(e).__name__ + ":" + str(e))[:80]
    try:
        r["a"] = sorted({x.address for x in dns.resolver.resolve(d, "A")})[:3]
    except Exception:
        r["a"] = []
    try:
        spf = [t.to_text() for t in dns.resolver.resolve(d, "TXT") if "v=spf1" in t.to_text()]
        r["spf"] = spf[0][:120] if spf else None
    except Exception:
        r["spf"] = None
    target = (hosts or r["a"] or [None])[0]
    if not target:
        r["smtp25"] = "skip"
        r["verdict"] = "NO_MX_NO_A"
    else:
        r["target"] = target
        try:
            s = socket.create_connection((target, 25), timeout=6)
            banner = s.recv(200).decode(errors="ignore").strip()
            s.close()
            r["smtp25_banner"] = banner[:80]
            if banner[:1] == "4":
                r["verdict"] = "DEFER_4XX_GREYLIST"
            elif banner[:1] == "2":
                r["verdict"] = "PORT25_OPEN"
            else:
                r["verdict"] = "UNEXPECTED_BANNER"
        except Exception as e:
            r["smtp25_error"] = type(e).__name__
            r["verdict"] = "PORT25_FAIL"
    out.append(r)
print(json.dumps(out, ensure_ascii=False))
