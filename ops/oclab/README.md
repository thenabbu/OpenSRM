# ops/oclab — what runs on the oclab host

`oclab` is the Oracle Always Free VPS that runs production
(`srm.200871.xyz`). Files here are installed on that host, not in a
container. The repo copy exists so a rebuilt host gets the same files back.

## opensrm-push-tick (class-reminder tick)

Drives `POST /internal/push/tick` once per minute from the box itself.
It replaces the Hermes cron job and the cron-job.org job of the same name,
and both of those stay disabled as fallbacks. Reference:
[docs/push.md](../../docs/push.md#tick-scheduler-live-cron-on-oclab).

Install on the host:

```bash
scp ops/oclab/opensrm-push-tick.sh oracle:/tmp/
scp ops/oclab/opensrm-push-tick.cron oracle:/tmp/
ssh oracle 'sudo install -m 755 /tmp/opensrm-push-tick.sh /usr/local/bin/opensrm-push-tick.sh'
ssh oracle 'sudo install -m 644 -o root -g root /tmp/opensrm-push-tick.cron /etc/cron.d/opensrm-push-tick'
```

Make sure that the install works:

```bash
ssh oracle 'sudo /usr/local/bin/opensrm-push-tick.sh; echo $?; sudo tail -2 /var/log/opensrm-push-tick.log'
```

A healthy line looks like this:

```
2026-11-27T07:46:01+05:30 200 {"audited":0,...,"mode":"live","ok":true,...}
```

`mode` must be `live` in production, and `ok` must be `true`. An `audited`
count of 0 means that no device has reminders switched on, which is data
rather than a fault.
