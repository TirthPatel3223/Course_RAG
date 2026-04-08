"""
Google Drive Setup Script — Interactive helper for first-time configuration.

This script guides you through:
1. Setting up Google Cloud project + Drive API
2. OAuth credentials download
3. First-time authentication
4. Creating the folder structure on Drive

Run: python scripts/setup_drive.py
"""

import sys
import json
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def print_header(text: str):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def print_step(step: int, text: str):
    print(f"\n  📌 Step {step}: {text}")
    print(f"  {'-'*50}")


def wait_for_user(prompt: str = "Press Enter to continue..."):
    input(f"\n  ⏩ {prompt}")


def main():
    print_header("Course RAG — Google Drive Setup Wizard")
    print("  This wizard will help you set up Google Drive integration")
    print("  for your Course RAG pipeline.\n")

    # ──────────────────────────────────────────
    # STEP 1: Google Cloud Project
    # ──────────────────────────────────────────
    print_step(1, "Create a Google Cloud Project")
    print("""
    1. Go to: https://console.cloud.google.com
    2. Sign in with your g.ucla.edu account
    3. Click the project dropdown at the top → 'New Project'
    4. Name it: 'Course-RAG'
    5. Click 'Create'
    6. Make sure the project is selected in the dropdown
    """)
    wait_for_user("Press Enter once your project is created...")

    # ──────────────────────────────────────────
    # STEP 2: Enable Drive API
    # ──────────────────────────────────────────
    print_step(2, "Enable the Google Drive API")
    print("""
    1. In the Google Cloud Console, go to:
       'APIs & Services' → 'Library'
       (or visit: https://console.cloud.google.com/apis/library)
    2. Search for 'Google Drive API'
    3. Click on it → Click 'ENABLE'
    """)
    wait_for_user("Press Enter once the Drive API is enabled...")

    # ──────────────────────────────────────────
    # STEP 3: Configure OAuth Consent Screen
    # ──────────────────────────────────────────
    print_step(3, "Configure OAuth Consent Screen")
    print("""
    1. Go to: 'APIs & Services' → 'OAuth consent screen'
       (or visit: https://console.cloud.google.com/apis/credentials/consent)

    2. Choose User Type:
       - If 'Internal' is available → Select 'Internal' (recommended for school accounts)
       - If only 'External' is available → Select 'External'

    3. Fill in the required fields:
       - App name: 'Course RAG'
       - User support email: your g.ucla.edu email
       - Developer contact: your g.ucla.edu email

    4. Click 'Save and Continue'

    5. On the 'Scopes' page:
       - Click 'Add or Remove Scopes'
       - Search for and add: 'Google Drive API .../auth/drive'
       - Click 'Update' then 'Save and Continue'

    6. If External: Add your g.ucla.edu email as a test user

    7. Click 'Save and Continue' → 'Back to Dashboard'
    """)
    wait_for_user("Press Enter once the consent screen is configured...")

    # ──────────────────────────────────────────
    # STEP 4: Create OAuth Credentials
    # ──────────────────────────────────────────
    print_step(4, "Create OAuth 2.0 Credentials")

    credentials_dir = PROJECT_ROOT / "credentials"
    credentials_dir.mkdir(parents=True, exist_ok=True)
    credentials_path = credentials_dir / "oauth_credentials.json"

    print(f"""
    1. Go to: 'APIs & Services' → 'Credentials'
       (or visit: https://console.cloud.google.com/apis/credentials)

    2. Click '+ CREATE CREDENTIALS' → 'OAuth client ID'

    3. Application type: 'Desktop app'

    4. Name: 'Course RAG Desktop'

    5. Click 'CREATE'

    6. Click 'DOWNLOAD JSON' (⬇️ button)

    7. Save the downloaded file as:
       {credentials_path}

       (Rename the downloaded file to 'oauth_credentials.json'
        and move it to the 'credentials/' folder in your project)
    """)
    wait_for_user("Press Enter once you've saved the credentials JSON file...")

    # Verify credentials file exists
    if not credentials_path.exists():
        print(f"\n  ⚠️  WARNING: Credentials file not found at:")
        print(f"      {credentials_path}")
        print(f"\n  Please make sure the file is saved at that exact path.")
        resp = input("\n  Try to continue anyway? (y/n): ").strip().lower()
        if resp != "y":
            print("\n  Exiting. Please save the credentials file and re-run.")
            sys.exit(1)
    else:
        # Validate JSON format
        try:
            with open(credentials_path) as f:
                cred_data = json.load(f)
            if "installed" in cred_data or "web" in cred_data:
                print("  ✅ Credentials file found and valid!")
            else:
                print("  ⚠️  Credentials file found but format may be incorrect.")
                print("     Expected 'installed' or 'web' key in JSON.")
        except json.JSONDecodeError:
            print("  ⚠️  Credentials file is not valid JSON. Please re-download.")

    # ──────────────────────────────────────────
    # STEP 5: Authenticate
    # ──────────────────────────────────────────
    print_step(5, "Authenticate with Google Drive")
    print("""
    A browser window will open for you to sign in with your
    g.ucla.edu account and authorize the app.

    After signing in, you'll be redirected back to this script.
    """)
    wait_for_user("Press Enter to start authentication...")

    try:
        from backend.services.drive_service import DriveService

        drive = DriveService()
        drive.authenticate()
        print("\n  ✅ Authentication successful!")
    except FileNotFoundError as e:
        print(f"\n  ❌ Error: {e}")
        print("  Please ensure the credentials file is in place and try again.")
        sys.exit(1)
    except Exception as e:
        print(f"\n  ❌ Authentication failed: {e}")
        print("  This might be because:")
        print("    - The consent screen isn't configured correctly")
        print("    - Your school admin has restricted third-party app access")
        print("    - The credentials file is invalid")
        sys.exit(1)

    # ──────────────────────────────────────────
    # STEP 6: Create Folder Structure
    # ──────────────────────────────────────────
    print_step(6, "Create Folder Structure on Drive")
    print("""
    Creating the folder structure for your courses...
    """)

    try:
        folders = drive.initialize_folder_structure()
        print(f"\n  ✅ Created/verified {len(folders)} folders:")
        for path, folder_id in sorted(folders.items()):
            print(f"     📁 {path}")
    except Exception as e:
        print(f"\n  ❌ Failed to create folders: {e}")
        sys.exit(1)

    # ──────────────────────────────────────────
    # STEP 7: Verify
    # ──────────────────────────────────────────
    print_step(7, "Verify Setup")

    try:
        tree = drive.get_folder_tree(max_depth=3)
        print("\n  📂 Your Drive folder structure:")
        _print_tree(tree, indent=4)
    except Exception as e:
        print(f"\n  ⚠️  Could not fetch tree: {e}")

    # ──────────────────────────────────────────
    # Done!
    # ──────────────────────────────────────────
    print_header("Setup Complete! 🎉")
    print("  Your Google Drive is now configured for Course RAG.")
    print(f"\n  Root folder: {drive._root_folder_name}")
    print(f"  Token saved: {drive._token_path}")
    print("\n  Next steps:")
    print("    1. Upload your course files to the appropriate folders on Drive")
    print("    2. Run the embedding pipeline to index your documents")
    print("    3. Start the Course RAG server\n")


def _print_tree(node: dict, indent: int = 0):
    """Pretty-print a folder tree."""
    prefix = " " * indent
    if node["type"] == "folder":
        icon = "📁"
        children = node.get("children", [])
        print(f"{prefix}{icon} {node['name']}/")
        for child in children:
            _print_tree(child, indent + 3)
    else:
        icon = "📄"
        size = node.get("size", "?")
        print(f"{prefix}{icon} {node['name']} ({size} bytes)")


if __name__ == "__main__":
    main()
