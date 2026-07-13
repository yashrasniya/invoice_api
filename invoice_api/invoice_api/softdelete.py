"""
Soft delete: `delete()` marks rows as deleted instead of removing them.

- `Model.objects`      → live rows only (all views/aggregations use this)
- `Model.all_objects`  → everything, including deleted (admin/recovery)
- `instance.delete()`  → sets is_deleted/deleted_at (also for querysets)
- `instance.hard_delete()` / `qs.hard_delete()` → real removal (internal use)
- `instance.restore()` → undelete
"""
from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        return super().update(is_deleted=True, deleted_at=timezone.now())

    def hard_delete(self):
        return super().delete()

    def restore(self):
        return super().update(is_deleted=False, deleted_at=None)


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)


class AllObjectsManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db)


class SoftDeleteModel(models.Model):
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()      # default: live rows only
    all_objects = AllObjectsManager()  # includes deleted

    class Meta:
        abstract = True
        # FK traversal & internals must see all rows
        base_manager_name = 'all_objects'

    def delete(self, *args, **kwargs):
        if self.is_deleted:
            return
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=['is_deleted', 'deleted_at'])

    def hard_delete(self, *args, **kwargs):
        return super().delete(*args, **kwargs)

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=['is_deleted', 'deleted_at'])
