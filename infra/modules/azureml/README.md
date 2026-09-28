# azureml

Azure Machine Learning workspace (Basic) that reuses the project's Application
Insights and container registry, with its own storage account and access-policy
Key Vault, plus a CPU compute cluster that scales 0-1 nodes.

Training runs as a command job (`ml/aml/train-job.yml`); passing models are
registered as `dfcast-lgbm` in the workspace model registry and deploy.yml pulls
a registered version into the image.
