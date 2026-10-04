"""Typed run details, lap/zone children and compact streams."""

from alembic import op

revision = "0003_run_data"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE activity_details (
    activity_id VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    raw_summary JSONB,
    state VARCHAR NOT NULL,
    attempts INTEGER NOT NULL,
    error VARCHAR,
    fetched_at TIMESTAMP WITH TIME ZONE,
    fit_name VARCHAR,
    moving_time_s NUMERIC,
    elapsed_time_s NUMERIC,
    average_pace_s_km NUMERIC,
    max_pace_s_km NUMERIC,
    average_speed_m_s NUMERIC,
    max_speed_m_s NUMERIC,
    max_hr NUMERIC,
    average_cadence_spm NUMERIC,
    max_cadence_spm NUMERIC,
    stride_length_cm NUMERIC,
    vertical_oscillation_cm NUMERIC,
    vertical_ratio_percent NUMERIC,
    ground_contact_time_ms NUMERIC,
    average_power_w NUMERIC,
    max_power_w NUMERIC,
    normalized_power_w NUMERIC,
    elevation_gain_m NUMERIC,
    elevation_loss_m NUMERIC,
    min_elevation_m NUMERIC,
    max_elevation_m NUMERIC,
    average_temperature_c NUMERIC,
    min_temperature_c NUMERIC,
    max_temperature_c NUMERIC,
    calories NUMERIC,
    aerobic_training_effect NUMERIC,
    anaerobic_training_effect NUMERIC,
    training_load NUMERIC,
    vo2_max NUMERIC,
    started_at TIMESTAMP WITH TIME ZONE,
    timezone VARCHAR,
    device VARCHAR,
    PRIMARY KEY (activity_id),
    FOREIGN KEY(activity_id) REFERENCES activities (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE TABLE activity_laps (
    activity_id VARCHAR NOT NULL,
    position INTEGER NOT NULL,
    distance_m NUMERIC NOT NULL,
    duration_s NUMERIC NOT NULL,
    average_pace_s_km NUMERIC,
    average_hr NUMERIC,
    max_hr NUMERIC,
    average_cadence_spm NUMERIC,
    elevation_gain_m NUMERIC,
    elevation_loss_m NUMERIC,
    average_power_w NUMERIC,
    max_power_w NUMERIC,
    PRIMARY KEY (activity_id, position),
    FOREIGN KEY(activity_id) REFERENCES activities (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE TABLE activity_splits (
    activity_id VARCHAR NOT NULL,
    position INTEGER NOT NULL,
    distance_m NUMERIC NOT NULL,
    duration_s NUMERIC NOT NULL,
    average_pace_s_km NUMERIC,
    average_hr NUMERIC,
    max_hr NUMERIC,
    average_cadence_spm NUMERIC,
    elevation_gain_m NUMERIC,
    elevation_loss_m NUMERIC,
    average_power_w NUMERIC,
    max_power_w NUMERIC,
    PRIMARY KEY (activity_id, position),
    FOREIGN KEY(activity_id) REFERENCES activities (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE TABLE activity_hr_zones (
    activity_id VARCHAR NOT NULL,
    position INTEGER NOT NULL,
    zone INTEGER NOT NULL,
    seconds NUMERIC NOT NULL,
    lower_bpm NUMERIC,
    upper_bpm NUMERIC,
    PRIMARY KEY (activity_id, position),
    FOREIGN KEY(activity_id) REFERENCES activities (id) ON DELETE CASCADE
)
""")
    op.execute("""
CREATE TABLE activity_streams (
    activity_id VARCHAR NOT NULL,
    format VARCHAR NOT NULL,
    data BYTEA NOT NULL,
    PRIMARY KEY (activity_id),
    FOREIGN KEY(activity_id) REFERENCES activities (id) ON DELETE CASCADE
)
""")


def downgrade():
    op.drop_table("activity_streams")
    op.drop_table("activity_hr_zones")
    op.drop_table("activity_splits")
    op.drop_table("activity_laps")
    op.drop_table("activity_details")
