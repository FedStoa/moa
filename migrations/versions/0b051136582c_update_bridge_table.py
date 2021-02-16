"""update bridge table

Revision ID: 0b051136582c
Revises: 3ac471544742
Create Date: 2021-02-14 22:51:03.352845

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0b051136582c'
down_revision = '3ac471544742'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('bridge', sa.Column('gitlab_access_code', sa.String(length=80), nullable=True))
    op.add_column('bridge', sa.Column('gitlab_account_id', sa.BigInteger(), nullable=True))
    op.add_column('bridge', sa.Column('gitlab_handle', sa.String(length=30), nullable=True))
    op.add_column('settings', sa.Column('gitlab_project', sa.String(length=100), nullable=False, default=""))
    op.add_column('settings', sa.Column('post_to_gitlab', sa.Boolean, nullable=False, default=True))


def downgrade():
    op.drop_column('bridge', 'gitlab_access_code')
    op.drop_column('bridge', 'gitlab_account_id')
    op.drop_column('bridge', 'gitlab_handle')
    op.drop_column('settings', 'gitlab_project')
    op.drop_column('settings', 'post_to_gitlab')