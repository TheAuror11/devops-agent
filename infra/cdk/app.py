#!/usr/bin/env python3
from aws_cdk import App, Environment
from stack import DevOpsAgentStack

app = App()
DevOpsAgentStack(
    app,
    "DevOpsAgentStack",
    env=Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1",
    ),
)
app.synth()
