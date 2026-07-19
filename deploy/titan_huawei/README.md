# Titan Huawei edge deployment

This deployment keeps the GPU workload on AutoDL and exposes only an isolated
Huawei Cloud edge. All Huawei-side files live under `/home/softcup/titan`.

## Port allocation

- `20081/tcp`: public visitor HTTPS
- `20082/tcp`: public admin HTTPS
- `20083/tcp,udp`: TURN listener (only TCP is currently advertised)
- `20101/tcp`: loopback-only reverse SSH upstream for AutoDL port 8001
- `20111/tcp`: loopback-only reverse SSH upstream for AutoDL port 8011
- `20200-20399/udp`: coturn relay allocation range

Ports `20443` and `20444` are explicitly outside this deployment and must not
be modified. The installer also refuses its initial deployment if a requested
port is already occupied.

## Runtime files

- Huawei credentials and public URL settings:
  `/home/softcup/titan/runtime/direct.env` (mode 0600)
- AutoDL copy of the same settings: `deploy/direct.env` (git-ignored, mode 0600)
- Dedicated AutoDL SSH key: `/root/.ssh/cup_titan_huawei_ed25519`
- AutoDL tunnel start helper: `deploy/start_titan_huawei_tunnel.sh`

The SSH key is restricted on Huawei Cloud to remote forwarding on loopback
ports 20101 and 20111 and cannot open an interactive shell.

Huawei Cloud currently accepts TURN over TCP but drops external UDP even
though coturn's local UDP listener is healthy. Keep `TURN_UDP_ENABLED=false`
until the security group admits UDP 20083 and UDP 20200-20399 end to end.
