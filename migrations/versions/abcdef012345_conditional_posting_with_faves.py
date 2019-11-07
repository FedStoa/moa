"""empty message

Revision ID: abcdef012345
Revises: 52a6ff8551e1
Create Date: 2019-03-10 20:44:12.345678

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'abcdef012345'
down_revision = '52a6ff8551e1'
branch_labels = None
depends_on = None


def upgrade():
    ## Rename existing conditional_posting column for clarity.
    # op.alter_column('settings', 'conditional_posting', new_column_name='conditional_posting_hashtags')
    op.add_column('settings', sa.Column('conditional_posting_faves', sa.Boolean(), nullable=False))


def downgrade():
    ## Should be dropped in dc37a95190f6, provided it's correctly renamed back.
    # op.alter_column('settings', 'conditional_posting_hashtags', new_column_name='conditional_posting')
    op.drop_column('settings', 'conditional_posting_faves')
    