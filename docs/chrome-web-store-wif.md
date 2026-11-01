# Chrome Web Store API authentication with GitHub Actions WIF

The Growth Agent uses GitHub Actions OIDC and Google Cloud Workload Identity Federation. It does not use a service-account JSON key.

## Google Cloud Console setup

Use project `growth-agent-513404` (`422137694636`).

1. Open **IAM & Admin → Workload Identity Federation**.
2. Create pool `github-actions` in `global`.
3. Add OIDC provider `errrt-github` with issuer `https://token.actions.githubusercontent.com/` and the default audience.
4. Configure these attribute mappings:

   ```text
   google.subject=assertion.sub
   attribute.repository_id=assertion.repository_id
   attribute.repository_owner_id=assertion.repository_owner_id
   attribute.repository=assertion.repository
   attribute.ref=assertion.ref
   ```

5. Configure this provider attribute condition:

   ```text
   assertion.repository_owner_id == '28991374' &&
   assertion.repository_id == '1424815965' &&
   assertion.repository == 'errrt/errrt.github.io' &&
   assertion.ref == 'refs/heads/main'
   ```

6. Grant service-account impersonation to `errrt-growth-agent@growth-agent-513404.iam.gserviceaccount.com` using only **Workload Identity User** (`roles/iam.workloadIdentityUser`).
7. Restrict the grant to:

   ```text
   principalSet://iam.googleapis.com/projects/422137694636/locations/global/workloadIdentityPools/github-actions/attribute.repository_id/1424815965
   ```

Do not grant Editor, Owner, or Service Account Token Creator. Do not create or download a JSON key.

## GitHub repository variables

Configure these under **Settings → Secrets and variables → Actions → Variables**:

| Name | Value |
|---|---|
| `GCP_WIF_PROVIDER` | `projects/422137694636/locations/global/workloadIdentityPools/github-actions/providers/errrt-github` |
| `GCP_CWS_SERVICE_ACCOUNT` | `errrt-growth-agent@growth-agent-513404.iam.gserviceaccount.com` |
| `CWS_PUBLISHER_ID` | `455e9b45-2e98-4417-9cfd-a70152286cd4` |

These values are identifiers, not credentials. No GitHub Secret is required for Chrome Web Store authentication.

## Run the authentication test

The provider only accepts OIDC tokens for `refs/heads/main`. Therefore the authentication test cannot succeed from a pull-request branch by design.

After this workflow has been reviewed and merged separately:

1. Open **Actions → Chrome Web Store Auth Test**.
2. Select **Run workflow** on `main`.
3. Confirm that both PhraseCrate and Tab Parcel show `Success` in the job summary.

The workflow requests an access token with only `https://www.googleapis.com/auth/chromewebstore.readonly`, keeps it for five minutes, and does not create a credentials file.
