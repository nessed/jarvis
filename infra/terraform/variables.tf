variable "region" {
  description = "OCI region to provision in. A1 capacity is regional and often exhausted; this is the variable Ali retries on."
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment to create everything in. The tenancy root OCID is fine for a personal tenancy."
  type        = string
}

variable "availability_domain" {
  description = "Availability domain name, e.g. 'lfcb:AP-MUMBAI-1-AD-1'. Read it off `oci iam availability-domain list` on U7 day."
  type        = string
}

variable "ssh_public_key" {
  description = "Contents of the public half of the key pair. The private half never enters this repo."
  type        = string
}

# ---------------------------------------------------------------------------
# The 2/12 numbers are load-bearing, not defaults to tune.
#
# Oracle's Always Free ceiling for Ampere A1 is 4 OCPU / 24 GB across the whole
# tenancy. The 27 Aug 2026 provider audit (docs/audit/blueprint-drift.md,
# Oracle entry) records that since the 18 Aug enforcement date, over-limit
# instances are auto-terminated rather than merely refused -- so an instance
# provisioned above the line is not a billing surprise, it is a VPS that
# disappears with the bus on it. The blueprint says "provision at 2/12 from day
# one" for exactly this reason.
#
# 2/12 is half the tenancy ceiling on purpose: it leaves room to stand up a
# second instance for a cutover without tripping the limit.
# ---------------------------------------------------------------------------
variable "instance_ocpus" {
  description = "OCPUs for the bus instance. Do not raise without reading the comment above."
  type        = number
  default     = 2

  validation {
    condition     = var.instance_ocpus <= 2
    error_message = "Above 2 OCPUs this tenancy is over its Always Free ceiling and the instance is auto-terminated. See docs/audit/blueprint-drift.md."
  }
}

variable "instance_memory_gbs" {
  description = "Memory in GB for the bus instance. Do not raise without reading the comment above."
  type        = number
  default     = 12

  validation {
    condition     = var.instance_memory_gbs <= 12
    error_message = "Above 12 GB this tenancy is over its Always Free ceiling and the instance is auto-terminated. See docs/audit/blueprint-drift.md."
  }
}

variable "boot_volume_gbs" {
  description = "Boot volume size. Always Free block storage is 200 GB in total across all volumes."
  type        = number
  default     = 100
}

variable "instance_name" {
  description = "Display name for the instance and the resources around it."
  type        = string
  default     = "jarvis-bus"
}

variable "ssh_ingress_cidr" {
  description = "Who may reach port 22. Narrow this to Ali's address if his ISP gives him a stable one; 0.0.0.0/0 relies on key-only auth plus fail2ban."
  type        = string
  default     = "0.0.0.0/0"
}
