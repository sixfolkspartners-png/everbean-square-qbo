"""Approval email for draft-and-approve. Email-safe HTML (inline styles, literal
colors, table layout — Gmail/Outlook safe). One-click 'Review & approve' button
links to the /review/{token} page. Send via Resend (wired in Phase A)."""
from __future__ import annotations


def build_approval_email(org_name: str, date: str, drafts: list, review_url: str) -> tuple[str, str, str]:
    """Returns (subject, html, text)."""
    total_dep = sum(float(d["deposit"] or 0) for d in drafts)
    all_balanced = all(d["balanced"] for d in drafts if d["lines"])
    subject = f"Approve QuickBooks entries — {org_name}, {date}  (${total_dep:,.2f})"

    rows = ""
    for d in drafts:
        name = "Credit card" if d["batch"] == "cc" else "Cash"
        badge = ("#0a7a15", "#e8f6e8", "balanced") if d["balanced"] else ("#b7791f", "#fdf3dd", "review")
        rows += (
          f'<tr><td style="padding:8px 0;border-bottom:1px solid #efefec;font-weight:600;color:#0b0b0b;">{name} batch'
          f'<div style="color:#8a8a84;font-size:11px;font-weight:400;">{d["doc"]}</div></td>'
          f'<td align="right" style="padding:8px 0;border-bottom:1px solid #efefec;font-weight:600;color:#0b0b0b;white-space:nowrap;">${d["deposit"]}</td>'
          f'<td align="right" style="padding:8px 0;border-bottom:1px solid #efefec;white-space:nowrap;">'
          f'<span style="background:{badge[1]};color:{badge[0]};font-size:11px;font-weight:600;padding:2px 8px;border-radius:6px;">{badge[2]}</span></td></tr>')

    html = f"""<!doctype html><html><body style="margin:0;background:#f4f4f2;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f2;"><tr>
<td align="center" style="padding:24px 12px;"><table role="presentation" width="560" cellpadding="0" cellspacing="0" style="width:560px;max-width:560px;">
<tr><td style="font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="font-size:19px;font-weight:700;color:#0b0b0b;">Approve today's QuickBooks entries</div>
  <div style="font-size:13px;color:#52514e;margin:2px 0 16px;">{org_name} · {date}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
    style="background:#fff;border:1px solid #e6e6e4;border-radius:12px;">
    <tr><td style="padding:16px 18px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:13px;">{rows}</table>
      <div style="margin-top:14px;">
        <a href="{review_url}" style="display:inline-block;background:#0a7a15;color:#fff;font-weight:600;
          font-size:14px;text-decoration:none;padding:12px 24px;border-radius:9px;">Review &amp; approve →</a>
      </div>
      <div style="color:#8a8a84;font-size:11.5px;margin-top:12px;">
        {'All batches reconcile to the penny.' if all_balanced else 'One or more batches need review before posting.'}
        Nothing posts to QuickBooks until you approve.</div>
    </td></tr>
  </table>
  <div style="font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:11px;color:#a5a39d;margin-top:14px;">
    DailyLedger · draft-and-approve</div>
</td></tr></table></td></tr></table></body></html>"""

    text = (f"Approve QuickBooks entries — {org_name}, {date}\n\n" +
            "\n".join(f"  {('Credit card' if d['batch']=='cc' else 'Cash')} batch  {d['doc']}  "
                      f"${d['deposit']}  [{'balanced' if d['balanced'] else 'review'}]" for d in drafts) +
            f"\n\nReview & approve: {review_url}\nNothing posts to QuickBooks until you approve.")
    return subject, html, text
