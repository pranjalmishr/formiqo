"""Short-lived Vercel OIDC -> Google service-account federation.

The provider is restricted to this Vercel team/project, and the service account has
only Firestore data access. No service-account key or developer refresh token is
stored in the deployed bundle or Vercel project environment.
"""
import os
from google.auth import identity_pool


class VercelToken(identity_pool.SubjectTokenSupplier):
    def get_subject_token(self,context,request):
        from vercel.oidc import get_vercel_oidc_token_sync
        return get_vercel_oidc_token_sync()


def credentials():
    provider=os.environ['GCP_WIF_PROVIDER']
    service_account=os.environ['GCP_SERVICE_ACCOUNT_EMAIL']
    return identity_pool.Credentials(
        audience='//iam.googleapis.com/'+provider,
        subject_token_type='urn:ietf:params:oauth:token-type:jwt',
        token_url='https://sts.googleapis.com/v1/token',
        service_account_impersonation_url='https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/'+service_account+':generateAccessToken',
        subject_token_supplier=VercelToken(),
        scopes=['https://www.googleapis.com/auth/datastore'],
    )
