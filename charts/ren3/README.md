# Ren3 Deployment using Helm

This guide explains how to deploy the Ren3 application onto a Kubernetes cluster using a Helm chart.

## Prerequisites

Before you start, make sure you have the following set up in your AWS EKS cluster:

* **DNS Name:** A domain name (like `ren3.yourcompany.com`) ready to point to the application.
* **TLS Certificates:** SSL/TLS certificates for the domain name to enable secure HTTPS connections.
* **Nginx Ingress Controller:** Nginx ingress controller must be installed and configured to use your TLS certificates. This handles traffic coming into your cluster.
* **Storage CSI Driver:** A storage driver (like the AWS EBS CSI driver) must be installed so the application can store persistent data.

## Optional Components

These components are not required for Ren3 to run but can be helpful for observability:

* **Vault:** A secret management tool deployed and updated with the required configs to connect to ESO. 
* **External Secrets Operator (ESO):** ESO should be installed and set up to securely manage secrets, for example, by connecting to HashiCorp Vault.
* **Metrics Server:** Provides basic resource usage metrics for pods and nodes.
* **Alloy:** A lightweight service mesh alternative that can be used for traffic management and observability within the cluster.
* **kube-state-metrics & node-exporter:** Provide detailed cluster and node metrics for monitoring systems like Prometheus and Grafana.

## Deployment Steps

1.  **Configure `values.yaml`:**
    * Open the [values.yaml](values.yaml) file located in the same directory as the Helm chart.
    * Update the settings inside this file to match your specific environment. This will include things like the DNS name, resource settings, Vault URLs, and other Ren3 configurations.

2.  **Install the Helm Chart:**
    * Open your terminal or command line.
    * Navigate to the directory containing the Ren3 Helm chart (where the `Chart.yaml` and `values.yaml` files are).
    * Run the following command:

    ```bash
    helm upgrade --install ren3 ./ --namespace ren3 --create-namespace -f values.yaml
    ```

After running the command, Helm will deploy the Ren3 application to your EKS cluster according to the settings in `values.yaml`. You can check the status using `kubectl get pods -n ren3`.