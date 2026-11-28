"""Grant/revoke the sole GeoStudio administrator claim via trusted local ADC."""
import argparse
import re
import firebase_admin
from firebase_admin import auth

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.project):
        parser.error("Invalid project ID")
    app = firebase_admin.initialize_app(options={"projectId": args.project})
    email = input("Administrator Firebase account email: ").strip()
    user = auth.get_user_by_email(email, app=app)
    action = "REVOKE" if args.revoke else "GRANT"
    print("Project:", args.project, "| Account:", user.email)
    if input("Type "+action+" to confirm: ").strip() != action:
        print("Cancelled")
        return
    claims = dict(user.custom_claims or {})
    if args.revoke:
        claims.pop("admin", None)
    else:
        claims["admin"] = True
    auth.set_custom_user_claims(user.uid, claims or None, app=app)
    if args.revoke:
        auth.revoke_refresh_tokens(user.uid, app=app)
    else:
        print("ADMIN_UID="+user.uid)
        print("Set this value in the Admin Worker, not a password. Log out and back in.")
    print("OK")

if __name__ == "__main__":
    main()
