# terraform-provider-fspanos

A fork of the [Palo Alto Networks `panos` Terraform provider](https://github.com/PaloAltoNetworks/terraform-provider-panos)
carrying NGFW-clustering support that upstream does not yet have.

Published as `jibey-fs/fspanos` so it can be used from the registry alongside —
not instead of — the upstream provider.

```hcl
terraform {
  required_providers {
    panos = {
      source  = "jibey-fs/fspanos"
      version = "~> 2.1"
    }
  }
}
```

Everything else is identical to upstream `2.0.13`: same resources, same schema,
same behaviour. Only the three changes below are added.

## Why this fork exists

Managing a PA-5540 NGFW cluster through Panorama is not possible with upstream
2.0.13, and one of the gaps silently destroys existing configuration.

### 1. `enable_clustering` — upstream deletes it (data loss)

`settings` had exactly one declared child, `default-vsys`, so every write to a
template or template stack marshalled the whole node as

```xml
<settings><default-vsys>vsys1</default-vsys></settings>
```

and PAN-OS dropped the undeclared `<enable-clustering>`. Importing a
cluster-enabled template and applying a one-line description change was enough
to destroy it — no error, and the plan showed only the intended change.

The loss is permanent. PAN-OS accepts the flag only at creation ("You must
enable clustering when you first create the template; you can't go back to
enable clustering later"), so the object has to be deleted and rebuilt. A stack
whose flag no longer matches its template then rejects the pairing, and cluster
members cannot be attached to it at all.

This fork declares the parameter on `panos_template` and `panos_template_stack`,
so existing values survive a write and clustering can be set at creation.

### 2. `panos_cluster_ethernet_interface` — new resource

A template with clustering enabled does not use `network/interface/ethernet`:

```
ethernet -> ethernet1/9 'ethernet1/9' is invalid. Clustering is enabled.
```

Ports live under `network/interface/cluster-ethernet`, and each entry name
carries the owning cluster node, because MC-LAG members come from both nodes:

```hcl
resource "panos_cluster_ethernet_interface" "member" {
  location        = { template = { name = "FISH-CLUSTER", vsys = "vsys1" } }
  name            = "node1:ethernet1/9"
  aggregate_group = "ae1"
}
```

A bare name is rejected with `'ethernet1/9' is invalid. Invalid cluster ethernet`.

### 3. `template_stack_device` — per-device variable location

`panos_template_variable` had `template` and `template_stack` locations. The
third scope, where per-device values live, was missing:

```
/config/devices/entry[@name='...']/template-stack/entry[@name='STACK']
  /devices/entry[@name='SERIAL']/variable/entry[@name='$x']
```

Without it a variable resolves to one value for every member of a stack, so a
shared template cannot serve an HA pair or a cluster.

```hcl
resource "panos_template_variable" "router_id" {
  location = {
    template_stack_device = {
      template_stack = "FISH-HA-CLUSTER-MODE"
      device         = "033609000950"
    }
  }
  name = "$router-id"
  type = { ip_netmask = "10.0.0.1/32" }
}
```

Note PAN-OS requires the variable to be **declared at template level** before a
stack or device value is accepted; otherwise it returns
`'$router-id' is not a valid reference`.

## Verified against

Panorama 12.1.4-h3, PA-5540 cluster. Create and update of a cluster-enabled
template both preserve the flag; a cluster stack accepts its template and both
members; `node1:ethernet1/9` created with `aggregate_group = ae1`.

## Source

Generated from a fork of [pan-os-codegen](https://github.com/jibey-fs/pan-os-codegen)
(branch `cluster-support`) — the upstream provider is auto-generated, so the
changes are YAML spec edits, not hand-written Go. Each is also on its own branch
for upstreaming:

- `fix/template-enable-clustering`
- `feat/cluster-ethernet-interface`
- `feat/template-variable-device-location`

## Licence

MIT, as upstream. Copyright (c) 2020 Palo Alto Networks, inc. See `LICENSE`.
