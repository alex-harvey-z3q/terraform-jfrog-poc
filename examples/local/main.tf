terraform {
  required_version = ">= 1.5, < 2.0"
  required_providers {
    artifactory = {
      source  = "jfrog/artifactory"
      version = "= 12.11.13"
    }
  }
}

# Deliberately fixed to the disposable lab. Token is injected via environment.
provider "artifactory" {
  url = "http://localhost:8082"
}

module "security" {
  source = "../../modules/security-baseline"
}

output "baseline" {
  value = module.security.baseline
}
