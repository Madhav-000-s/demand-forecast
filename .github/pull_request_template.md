## What and why

<!-- One or two sentences. Link the issue if there is one. -->

## Type of change

- [ ] Application / API
- [ ] Model / training
- [ ] Infrastructure (Terraform)
- [ ] CI/CD / workflows
- [ ] Docs only

## Risk

- [ ] Low: no user-facing or infrastructure impact
- [ ] Medium: changes the API, model or a workflow step that deploys
- [ ] High: changes networking, identity, data, or anything that could cause downtime

What could break, and how would we notice (which alert or dashboard tile)?

## Rollback plan

<!-- e.g. "Revert this PR; deploy.yml re-releases the previous image as a canary",
     "Reactivate the previous revision: az containerapp revision activate ...",
     "terraform apply of the previous commit". -->

## Checks

- [ ] Tests added or updated
- [ ] `terraform plan` comment reviewed (infra changes)
- [ ] Runbook / docs updated if behaviour or alerts changed
