from django.db import migrations


class Migration(migrations.Migration):
    dependencies=[("scheduling","0004_professional_unit")]
    operations=[
        migrations.RenameIndex(model_name="appointment",old_name="scheduling__tenant__ef093f_idx",new_name="scheduling__tenant__012f99_idx"),
        migrations.RenameIndex(model_name="appointment",old_name="scheduling__tenant__fe8e3e_idx",new_name="scheduling__tenant__d04a39_idx"),
        migrations.RenameIndex(model_name="appointmentreminderlog",old_name="sched_reminder_status_idx",new_name="scheduling__tenant__f649c2_idx"),
        migrations.RenameIndex(model_name="appointmentreschedulehistory",old_name="sched_reschedule_idx",new_name="scheduling__tenant__0a290d_idx"),
        migrations.RenameIndex(model_name="customer",old_name="scheduling__tenant__e3124e_idx",new_name="scheduling__tenant__1e1fae_idx"),
        migrations.RenameIndex(model_name="customer",old_name="scheduling__tenant__2d72c4_idx",new_name="scheduling__tenant__965dee_idx"),
        migrations.RenameIndex(model_name="professionalbreak",old_name="sched_break_tenant_prof_idx",new_name="scheduling__tenant__dc68fd_idx"),
        migrations.RenameIndex(model_name="professionaltimeoff",old_name="sched_timeoff_range_idx",new_name="scheduling__tenant__0b5bab_idx"),
    ]
