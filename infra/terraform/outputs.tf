output "public_ip" {
  description = "Where to SSH. Feed this straight into scripts/harden.sh."
  value       = oci_core_instance.bus.public_ip
}

output "ssh_command" {
  description = "The exact command for the next runbook step, so nothing is retyped."
  value       = "ssh -i <private-key> ubuntu@${oci_core_instance.bus.public_ip}"
}

output "shape_actually_provisioned" {
  description = "Read this back before walking away. Anything other than 2 / 12 is auto-terminated later."
  value = {
    ocpus         = oci_core_instance.bus.shape_config[0].ocpus
    memory_in_gbs = oci_core_instance.bus.shape_config[0].memory_in_gbs
  }
}

output "image_used" {
  description = "Which Ubuntu image the data source picked, recorded so a later rebuild is reproducible."
  value       = data.oci_core_images.ubuntu_arm.images[0].display_name
}
