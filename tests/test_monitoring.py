"""Monitoring stays opt-in, passive and separate from the production daemon."""
from pathlib import Path
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / 'roles/dcmcp'


class MonitoringTests(unittest.TestCase):
    def test_monitor_templates_are_passive_and_use_nonroot_runtime_identity(self):
        engine = Environment(undefined=StrictUndefined)
        variables = dict(dcmcp_user='alice', dcmcp_gid='1001',
                         dcmcp_home='/var/lib/desktop-commander-mcp/home',
                         dcmcp_helpers='/usr/local/libexec/desktop-commander-mcp')
        service = engine.from_string((ROLE / 'templates/desktop-commander-mcp-health.service.j2')
                                     .read_text()).render(**variables)
        timer = engine.from_string((ROLE / 'templates/desktop-commander-mcp-health.timer.j2')
                                   .read_text()).render(**variables)
        self.assertIn('Type=oneshot', service)
        self.assertIn('User=alice', service)
        self.assertIn('Group=1001', service)
        self.assertIn('NoNewPrivileges=true', service)
        self.assertIn('ExecStart=/usr/bin/python3 /usr/local/libexec/desktop-commander-mcp/doctor.py --json', service)
        self.assertIn('OnUnitActiveSec=5min', timer)
        self.assertIn('Persistent=false', timer)
        self.assertIn('WantedBy=timers.target', timer)
        for prohibited in ('Restart=', 'OnFailure=', 'ExecStartPost=', 'ExecStop=',
                           'sudo', 'curl', 'systemctl restart'):
            self.assertNotIn(prohibited, service + timer)

    def test_monitor_role_never_restarts_main_service(self):
        enable = yaml.safe_load((ROLE / 'tasks/monitor-enable.yml').read_text())
        disable = yaml.safe_load((ROLE / 'tasks/monitor-disable.yml').read_text())
        self.assertEqual(enable[0]['ansible.builtin.import_tasks'], 'context.yml')
        self.assertEqual(disable[0]['ansible.builtin.import_tasks'], 'context.yml')
        self.assertTrue(any('monitoring timer' in task['name'] for task in enable))
        self.assertTrue(any('monitoring timer' in task['name'] for task in disable))
        for task in enable + disable:
            module = task.get('ansible.builtin.systemd_service', {})
            self.assertNotEqual(module.get('state'), 'restarted')
            if module.get('state') in ('started', 'stopped'):
                self.assertEqual(module.get('name'), 'desktop-commander-mcp-health.timer')
        self.assertIn('monitor-disable.yml', (ROLE / 'tasks/uninstall.yml').read_text())

    def test_monitor_is_opt_in_not_part_of_install_or_activate(self):
        for task_name in ('main.yml', 'activate.yml', 'deactivate.yml'):
            text = (ROLE / 'tasks' / task_name).read_text()
            self.assertNotIn('monitor-enable.yml', text)
            self.assertNotIn('health.timer', text)
        for name in ('monitor-enable.yml', 'monitor-disable.yml'):
            play = yaml.safe_load((ROOT / 'playbooks' / name).read_text())[0]
            self.assertEqual(play['hosts'], 'mcp_servers')
            self.assertTrue(play['become'])
            self.assertEqual(play['serial'], 1)


if __name__ == '__main__':
    unittest.main()
