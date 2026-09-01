# One Always Free Ampere A1 instance, and the minimum network around it.
#
# Deliberately not here: a load balancer, a second subnet, a NAT gateway, a
# bastion, DNS. Phase 4 moves one FastAPI process off a laptop. Anything more
# is a second thing to debug on a day whose whole point is that the design is
# already done.
#
# No inbound port is opened for the bus itself. The webhook arrives through a
# Cloudflare named tunnel, which dials *out* from the VPS -- so the only
# listening port on the public internet is SSH. See scripts/install-cloudflared.sh.

# Canonical's own Ubuntu ARM image for this region. A hardcoded image OCID is
# region-specific and goes stale every few weeks; this looks the current one up
# at plan time instead.
data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_vcn" "jarvis" {
  compartment_id = var.compartment_ocid
  display_name   = "${var.instance_name}-vcn"
  cidr_blocks    = ["10.0.0.0/16"]
  dns_label      = "jarvis"
}

resource "oci_core_internet_gateway" "jarvis" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.jarvis.id
  display_name   = "${var.instance_name}-igw"
  enabled        = true
}

resource "oci_core_route_table" "jarvis" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.jarvis.id
  display_name   = "${var.instance_name}-rt"

  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_internet_gateway.jarvis.id
  }
}

# OCI security lists are stateful, so a single egress rule covers the return
# traffic for the tunnel's outbound connection. ufw on the host is the second
# layer; see scripts/harden.sh.
resource "oci_core_security_list" "jarvis" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.jarvis.id
  display_name   = "${var.instance_name}-sl"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  ingress_security_rules {
    source      = var.ssh_ingress_cidr
    protocol    = "6" # TCP
    description = "SSH. The only port open to the internet; the webhook comes through the tunnel."

    tcp_options {
      min = 22
      max = 22
    }
  }
}

resource "oci_core_subnet" "jarvis" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.jarvis.id
  display_name      = "${var.instance_name}-subnet"
  cidr_block        = "10.0.1.0/24"
  route_table_id    = oci_core_route_table.jarvis.id
  security_list_ids = [oci_core_security_list.jarvis.id]
  dns_label         = "bus"
}

resource "oci_core_instance" "bus" {
  compartment_id      = var.compartment_ocid
  availability_domain = var.availability_domain
  display_name        = var.instance_name
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_gbs
  }

  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = var.boot_volume_gbs
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.jarvis.id
    assign_public_ip = true
    hostname_label   = "bus"
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
  }

  # An A1 shape change is destructive and there is exactly one right answer
  # (see variables.tf). This turns a fat-fingered apply into an error instead
  # of a rebuild of the machine the assistant runs on.
  lifecycle {
    prevent_destroy = true
  }
}
