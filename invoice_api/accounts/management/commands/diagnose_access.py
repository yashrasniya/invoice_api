"""
Why can't this user do X? Walks the whole permission chain for one user.

    python manage.py diagnose_access --user yash
    python manage.py diagnose_access --user yash --perm subscription.manage
    python manage.py diagnose_access --user yash --fix-admin-role

Built for the "Upgrade button is greyed out in prod but works locally"
class of problem. The button is disabled when the frontend's
`permissions` array is missing `subscription.manage`, and that array comes
from /authz/me/ -> get_user_permissions(), which resolves through:

    catalog row -> role.permissions -> role.users -> direct grants/denies
                                                  -> cache

A break anywhere in that chain looks identical from the browser, so this
prints each link and names the one that failed.
"""
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

DEFAULT_PERM = 'subscription.manage'
ADMIN_ROLE = 'Company Admin'


class Command(BaseCommand):
    help = "Trace how a permission resolves for a user, and say why it doesn't."

    def add_arguments(self, parser):
        parser.add_argument('--user', required=True, help='username or email')
        parser.add_argument('--perm', default=DEFAULT_PERM,
                            help=f'permission code to trace (default {DEFAULT_PERM})')
        parser.add_argument('--fix-admin-role', action='store_true',
                            help='if the user has the legacy is_company_admin flag but '
                                 'is not in the Company Admin role, add them')

    def handle(self, *args, **opts):
        from accounts.models import (CompanyPermission, CompanyRole, User,
                                     UserDirectPermission)
        from invoice_api.middleware import get_user_permissions

        code = opts['perm']
        ident = opts['user']
        user = (User.objects.filter(username=ident).first()
                or User.objects.filter(email__iexact=ident).first())
        if not user:
            raise CommandError(f'No user matches {ident!r}.')

        company = user.user_company
        w = self.stdout.write
        ok, err, warn = self.style.SUCCESS, self.style.ERROR, self.style.WARNING

        w(self.style.MIGRATE_HEADING(f'USER  {user.username}  (id {user.id})'))
        w(f'  email            : {user.email or "—"}')
        w(f'  company          : {company.company_name if company else "NONE"}'
          f'{f" (id {company.id})" if company else ""}')
        w(f'  is_superuser     : {user.is_superuser}')
        w(f'  is_company_admin : {user.is_company_admin}   (legacy boolean)')

        if not company:
            w(err('\n  No company. Every company-scoped permission resolves to empty.'))
            return

        # ── 1. is the permission in the catalog at all? ──
        w(self.style.MIGRATE_HEADING(f'\n1. CATALOG — is {code!r} defined?'))
        perm = CompanyPermission.objects.filter(code=code, company=None).first()
        if perm:
            w(ok(f'  yes (id {perm.id}, system={perm.is_system_permission})'))
        else:
            w(err('  MISSING from the global catalog.'))
            w(err('  Nothing can grant a permission that does not exist. This is what\n'
                  '  it looks like when a migration that seeds it has not been applied.'))
            self.migration_hint()
            return

        # ── 2. which roles grant it, and is the user in one? ──
        w(self.style.MIGRATE_HEADING(f'\n2. ROLES in {company.company_name!r}'))
        roles = CompanyRole.objects.filter(company=company, is_deleted=False)
        if not roles.exists():
            w(err('  This company has NO roles — bootstrap never ran for it.'))

        user_role_names, granting_roles = [], []
        for role in roles:
            has_perm = role.permissions.filter(code=code).exists()
            has_user = role.users.filter(pk=user.pk).exists()
            if has_user:
                user_role_names.append(role.name)
            if has_perm:
                granting_roles.append(role.name)
            flag = ('  <-- user is in this role' if has_user else '')
            w(f'  {role.name:<22} grants {code}: {"YES" if has_perm else "no ":<4} '
              f'({role.permissions.count()} perms total){flag}')

        # global system roles (company=None) the user may hold
        for role in CompanyRole.objects.filter(company__isnull=True, is_deleted=False):
            if role.users.filter(pk=user.pk).exists():
                user_role_names.append(f'{role.name} (global)')
                if role.permissions.filter(code=code).exists():
                    granting_roles.append(f'{role.name} (global)')
                w(f'  {role.name+" (global)":<22} '
                  f'grants {code}: '
                  f'{"YES" if role.permissions.filter(code=code).exists() else "no"}'
                  f'  <-- user is in this role')

        w(f'\n  user is in roles : {user_role_names or "NONE"}')
        w(f'  roles granting it: {granting_roles or "NONE"}')

        # ── 3. direct grants / denies ──
        w(self.style.MIGRATE_HEADING('\n3. DIRECT OVERRIDES'))
        direct = list(UserDirectPermission.objects
                      .filter(user=user, company=company)
                      .select_related('permission'))
        mine = [d for d in direct if d.permission.code == code]
        if not direct:
            w('  none')
        for d in direct:
            marker = '  <-- applies to the traced permission' if d.permission.code == code else ''
            w(f'  {d.permission.code:<28} is_granted={d.is_granted}{marker}')
        if any(not d.is_granted for d in mine):
            w(err('  A direct DENY is present. Denies always win, whatever the roles say.'))

        # ── 4. what the resolver actually returns ──
        w(self.style.MIGRATE_HEADING('\n4. RESOLVED'))
        fresh = get_user_permissions(user, company, use_cache=False)
        cached_key_perms = get_user_permissions(user, company, use_cache=True)
        w(f'  fresh from DB : {len(fresh)} permissions, has {code}: {code in fresh}')
        w(f'  through cache : {len(cached_key_perms)} permissions, '
          f'has {code}: {code in cached_key_perms}')

        if (code in fresh) != (code in cached_key_perms):
            w(err('  DB and cache DISAGREE — a stale cached permission set is being served.\n'
                  '  With a per-process cache this only clears in the worker that ran the\n'
                  '  invalidation; check the CACHES backend.'))

        # ── verdict ──
        w(self.style.MIGRATE_HEADING('\nVERDICT'))
        if code in fresh:
            w(ok(f'  {user.username} HAS {code}.'))
            if code == DEFAULT_PERM:
                w('  The Upgrade button should be enabled — unless the plan card is the\n'
                  '  one you are already on (it renders as "Your plan" and stays disabled).')
                w('  If it is still greyed out in the browser, compare the `permissions`\n'
                  '  array in the live /authz/me/ response against the list above; a\n'
                  '  difference there is the cache, not the data.')
        else:
            w(err(f'  {user.username} does NOT have {code}. The button will be disabled.'))
            if not granting_roles:
                w(err('  Cause: no role in this company grants it.'))
                self.migration_hint()
            elif not set(user_role_names) & set(granting_roles):
                w(err(f'  Cause: the permission is granted by {granting_roles}, but the\n'
                      f'  user is only in {user_role_names or "no roles"}.'))
                if user.is_company_admin:
                    w(warn('  The legacy is_company_admin flag is set but the role\n'
                           '  membership is missing. get_user_permissions() reads ROLES,\n'
                           '  not that boolean, so the flag alone grants nothing.\n'
                           '  Re-run with --fix-admin-role to attach them.'))
            elif any(not d.is_granted for d in mine):
                w(err('  Cause: an explicit direct DENY overrides the role grant.\n'
                      '  Remove it under Access Control -> the user -> direct permissions.'))

        # ── optional repair ──
        if opts['fix_admin_role']:
            self.fix_admin_role(user, company, code)

    def migration_hint(self):
        from django.db.migrations.recorder import MigrationRecorder
        applied = MigrationRecorder.Migration.objects.filter(
            app='billing', name='0002_seed_subscription_manage_permission').first()
        self.stdout.write(self.style.MIGRATE_HEADING('\n  MIGRATION CHECK'))
        if applied:
            self.stdout.write(
                f'  billing.0002_seed_subscription_manage_permission applied '
                f'{applied.applied}')
            self.stdout.write(
                '  It grants subscription.manage to every role named exactly\n'
                f'  {ADMIN_ROLE!r}. A renamed or custom admin role is skipped by it.')
        else:
            self.stdout.write(self.style.ERROR(
                '  billing.0002_seed_subscription_manage_permission is NOT applied.\n'
                '  That migration is what backfills subscription.manage onto existing\n'
                '  tenants. Run:  python manage.py migrate'))

    def fix_admin_role(self, user, company, code):
        from accounts.models import CompanyPermission, CompanyRole
        from accounts.authz_seed import ensure_company_roles
        from invoice_api.middleware import bump_perm_version, get_user_permissions

        self.stdout.write(self.style.MIGRATE_HEADING('\n--fix-admin-role'))
        if not user.is_company_admin:
            self.stdout.write(self.style.ERROR(
                '  Refusing: is_company_admin is False. This flag is the only evidence\n'
                '  that the user is meant to be an admin; grant the role explicitly\n'
                '  under Access Control instead.'))
            return

        admin_role, _ = ensure_company_roles(CompanyRole, CompanyPermission, company)
        if not admin_role.users.filter(pk=user.pk).exists():
            admin_role.users.add(user)
            self.stdout.write(self.style.SUCCESS(
                f'  Added {user.username} to {admin_role.name!r}.'))
        else:
            self.stdout.write(f'  Already in {admin_role.name!r}.')

        # the role may predate newer permissions; top it up to the current set
        perm = CompanyPermission.objects.filter(code=code, company=None).first()
        if perm and not admin_role.permissions.filter(pk=perm.pk).exists():
            admin_role.permissions.add(perm)
            self.stdout.write(self.style.SUCCESS(
                f'  Granted {code} to {admin_role.name!r} '
                '(the role predated this permission).'))

        bump_perm_version(company.id)
        cache.delete(f'company_sub:{company.id}')
        fresh = get_user_permissions(user, company, use_cache=False)
        self.stdout.write(
            f'  now has {code}: {code in fresh}  ({len(fresh)} permissions)')
        self.stdout.write(self.style.WARNING(
            '  Caches bumped. If CACHES is LocMemCache this only affects THIS\n'
            '  process — restart the web workers, or switch to a shared backend.'))
