terraform {
  required_version = ">= 1.5, < 2.0"
  required_providers {
    artifactory = {
      source  = "jfrog/artifactory"
      version = "= 12.11.13"
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

output "baseline" {
  value = {
    anonymous_access   = false
    encryption_policy  = "REQUIRED"
    lockout_enabled    = true
    login_attempts     = var.login_attempts
    expiration_enabled = false
    password_max_age   = 90
    notification_email = false
  }
}
