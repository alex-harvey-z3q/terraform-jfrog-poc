terraform {
  required_version = ">= 1.5, < 2.0"
  required_providers {
    artifactory = {
      source  = "jfrog/artifactory"
      version = "= 12.11.13"
    }
    external = {
      source  = "hashicorp/external"
      version = "~> 2.3"
    }
  }
}

variable "login_attempts" {
  description = "Policy threshold; exact fifth-attempt behaviour requires live acceptance."
  type        = number
  default     = 5
  validation {
    condition     = var.login_attempts == 5
    error_message = "The Basic Security Configuration requires login_attempts = 5."
  }
}

resource "artifactory_general_security" "baseline" {
  enable_anonymous_access = false
  encryption_policy       = "REQUIRED"
  lifecycle {
    prevent_destroy = true
  }
}

resource "artifactory_user_lock_policy" "baseline" {
  name           = "security-poc-lockout"
  enabled        = true
  login_attempts = var.login_attempts
  lifecycle {
    prevent_destroy = true
  }
  # Both resources may touch global security configuration. Serialize writes.
  depends_on = [artifactory_general_security.baseline]
}

resource "artifactory_password_expiration_policy" "baseline" {
  name             = "security-poc-expiration"
  enabled          = false
  password_max_age = 90 # Inactive while enabled=false; required by the API.
  notify_by_email  = false
  lifecycle {
    prevent_destroy = true
  }
  depends_on = [artifactory_user_lock_policy.baseline]
}

# The Artifactory provider does not expose this global security flag.  Keep the
# desired value, observed value, and remediation lifecycle in Terraform rather
# than hiding an API write in an imperative hook.  The two scripts use the
# inherited token only through the process environment.
data "external" "resource_hiding" {
  program = ["${path.module}/../../scripts/read-resource-hiding.sh"]
}

resource "terraform_data" "resource_hiding" {
  triggers_replace = {
    desired  = "true"
    observed = data.external.resource_hiding.result.value
  }

  provisioner "local-exec" {
    command = "${path.module}/../../scripts/set-resource-hiding.sh"
    environment = {
      JFROG_URL = "http://localhost:8082"
    }
  }

  lifecycle {
    precondition {
      condition     = contains(["true", "false"], data.external.resource_hiding.result.value)
      error_message = "The resource-hiding API did not return a boolean value."
    }
  }

  depends_on = [artifactory_password_expiration_policy.baseline]
}

output "baseline" {
  value = {
    anonymous_access            = false
    encryption_policy           = "REQUIRED"
    lockout_enabled             = true
    login_attempts              = var.login_attempts
    expiration_enabled          = false
    password_max_age            = 90
    notification_email          = false
    hide_unauthorized_resources = true
  }
}
