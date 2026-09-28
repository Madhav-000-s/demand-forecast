# keyvault

Key Vault in RBAC mode, soft delete 7 days, purge protection off so the stack can be
destroyed and re-applied. The deploying identity gets Key Vault Secrets Officer and
writes the secrets passed in `secrets`.
