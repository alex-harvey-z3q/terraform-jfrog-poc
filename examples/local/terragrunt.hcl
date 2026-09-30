# Terragrunt 1.1 always executes in a cache; preserve module paths and pin state outside it.
terragrunt_version_constraint = "= 1.1.6"
terraform_version_constraint  = ">= 1.5, < 2.0"
terraform_binary              = "${get_terragrunt_dir()}/../../scripts/terraform-engine"
prevent_destroy               = true

locals {
  scripts = "${get_terragrunt_dir()}/../../scripts"
  python  = get_env("POC_PYTHON", "python3")
}

generate "local_backend" {
  path      = "backend.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<-EOF
    terraform {
      backend "local" {
        path = ${jsonencode("${get_terragrunt_dir()}/terraform.tfstate")}
      }
    }
  EOF
}

# Use the committed multi-platform checksums in every cache initialization.
generate "provider_lock" {
  path              = ".terraform.lock.hcl"
  if_exists         = "overwrite"
  disable_signature = true
  contents          = file("${get_terragrunt_dir()}/.terraform.lock.hcl")
}

terraform {
  source                   = "${get_terragrunt_dir()}/../..//examples/local"
  copy_terraform_lock_file = false
  exclude_from_copy = [
    ".git", ".local", ".env", "**/.terraform", "**/.terragrunt-cache",
    "**/terraform.tfstate*", "**/*.tfplan", "**/*.tfvars", "**/__pycache__"
  ]
  extra_arguments "preserve_provider_lock" {
    commands  = ["init"]
    arguments = ["-lockfile=readonly"]
  }

  before_hook "credentials_and_api" {
    commands = ["plan", "apply", "import"]
    execute  = [local.python, "${local.scripts}/poc.py", "preflight"]
  }

  before_hook "deployment_prerequisites" {
    commands = ["apply"]
    execute  = [local.python, "${local.scripts}/security.py", "preflight"]
  }

  # Ordered, success-only hooks. No configuration writes on plan or import.
  after_hook "apply_additional_security" {
    commands     = ["apply"]
    execute      = [local.python, "${local.scripts}/security.py", "apply"]
    run_on_error = false
  }

  after_hook "verify_terraform" {
    commands     = ["apply"]
    execute      = [local.python, "${local.scripts}/poc.py", "verify-managed"]
    run_on_error = false
  }

  after_hook "verify_deployment" {
    commands     = ["apply"]
    execute      = [local.python, "${local.scripts}/security.py", "check"]
    run_on_error = false
  }
}
