terraform {
  required_version = ">= 1.6, < 2"
  required_providers {
    yandex = {
      source  = "yandex-cloud/yandex"
      version = "= 0.241.0"
    }
  }
}
provider "yandex" {
  cloud_id  = var.cloud_id
  folder_id = var.folder_id
  zone      = var.zone
}
variable "cloud_id" { type = string }
variable "folder_id" { type = string }
variable "ssh_public_key" { type = string }
variable "ssh_cidr" {
  type = string
  validation {
    condition     = can(cidrhost(var.ssh_cidr, 0)) && var.ssh_cidr != "0.0.0.0/0"
    error_message = "Укажите свой IP/CIDR для SSH, не весь интернет."
  }
}
variable "bucket_name" { type = string }
variable "name" {
  type    = string
  default = "plusfolio-pilot"
}
variable "zone" {
  type    = string
  default = "ru-central1-d"
}
variable "database_disk_gb" {
  type    = number
  default = 10
}
variable "system_disk_gb" {
  type    = number
  default = 40
}
variable "memory_gb" {
  type    = number
  default = 4
}
variable "cpu_fraction" {
  type    = number
  default = 50
}
variable "retention_days" {
  type    = number
  default = 14
  validation {
    condition     = var.retention_days >= 2
    error_message = "Сохраняйте не менее двух суток резервных копий."
  }
}
data "yandex_compute_image" "ubuntu" { family = "ubuntu-2404-lts" }
resource "yandex_vpc_network" "own" { name = var.name }
resource "yandex_vpc_subnet" "own" {
  name           = var.name
  network_id     = yandex_vpc_network.own.id
  v4_cidr_blocks = ["10.50.0.0/24"]
}
resource "yandex_vpc_security_group" "own" {
  name       = var.name
  network_id = yandex_vpc_network.own.id
  ingress {
    protocol       = "TCP"
    port           = 22
    v4_cidr_blocks = [var.ssh_cidr]
  }
  ingress {
    protocol       = "TCP"
    port           = 80
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    protocol       = "TCP"
    port           = 443
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    protocol       = "ANY"
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "yandex_vpc_address" "public" {
  name = var.name
  external_ipv4_address { zone_id = var.zone }
}
resource "yandex_compute_disk" "system" {
  name     = "${var.name}-system"
  type     = "network-hdd"
  image_id = data.yandex_compute_image.ubuntu.id
  size     = var.system_disk_gb
  lifecycle { prevent_destroy = true }
}
resource "yandex_compute_disk" "database" {
  name = "${var.name}-database"
  type = "network-ssd"
  size = var.database_disk_gb
  lifecycle { prevent_destroy = true }
}
resource "yandex_iam_service_account" "backup" { name = "${var.name}-backup" }
resource "yandex_storage_bucket" "backups" {
  bucket                = var.bucket_name
  folder_id             = var.folder_id
  default_storage_class = "COLD"
  max_size              = 25 * 1024 * 1024 * 1024
  force_destroy         = false
  anonymous_access_flags {
    read        = false
    list        = false
    config_read = false
  }
  versioning { enabled = true }
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { CanonicalUser = yandex_iam_service_account.backup.id }
      Action    = ["s3:PutObject", "s3:GetObject", "s3:ListBucket", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts", "s3:ListBucketMultipartUploads"]
      Resource  = ["arn:aws:s3:::${var.bucket_name}", "arn:aws:s3:::${var.bucket_name}/plusfolio/pilot/*"]
    }]
  })
  lifecycle_rule {
    id                                     = "pilot-retention"
    prefix                                 = "plusfolio/pilot/"
    enabled                                = true
    abort_incomplete_multipart_upload_days = 1
    expiration { days = var.retention_days }
    noncurrent_version_expiration { days = var.retention_days }
  }
  lifecycle { prevent_destroy = true }
}
resource "yandex_compute_instance" "app" {
  name                      = var.name
  platform_id               = "standard-v3"
  allow_stopping_for_update = false
  resources {
    cores         = 2
    memory        = var.memory_gb
    core_fraction = var.cpu_fraction
  }
  boot_disk {
    disk_id     = yandex_compute_disk.system.id
    auto_delete = false
  }
  secondary_disk {
    disk_id     = yandex_compute_disk.database.id
    device_name = "plusfolio-data"
    auto_delete = false
  }
  network_interface {
    subnet_id          = yandex_vpc_subnet.own.id
    nat                = true
    nat_ip_address     = yandex_vpc_address.public.external_ipv4_address[0].address
    security_group_ids = [yandex_vpc_security_group.own.id]
  }
  metadata = {
    user-data = templatefile("${path.module}/cloud-init.yml.tftpl", { ssh_public_key = var.ssh_public_key })
  }
}
output "public_ip" { value = yandex_vpc_address.public.external_ipv4_address[0].address }
output "backup_bucket" { value = yandex_storage_bucket.backups.bucket }
output "backup_service_account_id" { value = yandex_iam_service_account.backup.id }
