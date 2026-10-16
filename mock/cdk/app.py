import os

import aws_cdk as cdk

from urr_mock_stack import UrrMockStack

app = cdk.App()
UrrMockStack(
    app,
    "UrrMockApi",
    # Region is fixed; account comes from the CLI profile (pass --profile aipoc-admin).
    env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="us-west-2"),
)
app.synth()
