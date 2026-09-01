terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
  }
}

# Credentials come from the OCI CLI config file Ali creates during the U7
# signup sitting, not from variables in this repo. Nothing here ever holds a
# key, a fingerprint, or a private key path in version control.
provider "oci" {
  region = var.region
}
