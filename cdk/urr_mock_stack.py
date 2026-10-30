"""Read-only mock of the NSIF API + CatCloud extension endpoints: REST API (API key) -> one Lambda.

A REST API (not an HTTP API) is used because API keys / usage plans are not available on HTTP APIs.
"""

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from constructs import Construct

LAMBDA_DIR = Path(__file__).resolve().parents[1] / "lambda"
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "'*'",
    "Access-Control-Allow-Headers": "'*'",
    "Access-Control-Allow-Methods": "'*'",
}


class UrrMockStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        log_group = logs.LogGroup(
            self,
            "MockApiFunctionLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        fn = _lambda.Function(
            self,
            "MockApiFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(
                str(LAMBDA_DIR), exclude=["__pycache__", "*.pyc", "data/generation_report.json"]
            ),
            memory_size=512,
            timeout=cdk.Duration.seconds(10),
            log_group=log_group,
            description="Mock NSIF + CatCloud API (synthetic students, real faculty)",
        )

        api = apigw.RestApi(
            self,
            "MockRestApi",
            rest_api_name="urr-mock-api",
            cloud_watch_role=False,  # do not touch the account-wide API Gateway CloudWatch role
            description="Read-only mock of the NSIF service and CatCloud endpoints (x-api-key required)",
            deploy_options=apigw.StageOptions(
                stage_name="prod", throttling_rate_limit=50, throttling_burst_limit=100
            ),
            # OPTIONS preflight is answered by API Gateway and never requires the key.
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["*"],
            ),
        )
        # Keep CORS headers on gateway-generated errors (e.g. 403 missing key), or browsers
        # report a CORS failure instead of the real status.
        for rid, rtype in (("Default4xx", apigw.ResponseType.DEFAULT_4_XX),
                           ("Default5xx", apigw.ResponseType.DEFAULT_5_XX)):
            api.add_gateway_response(rid, type=rtype, response_headers=CORS_HEADERS)

        # One greedy resource; the Lambda does the routing (static segments before {param} routes).
        proxy = api.root.add_resource("api").add_resource("v1").add_resource("{proxy+}")
        proxy.add_method(
            "ANY", apigw.LambdaIntegration(fn, proxy=True), api_key_required=True
        )

        key = api.add_api_key("MockApiKey", api_key_name="urr-mock-key")
        plan = api.add_usage_plan(
            "MockUsagePlan",
            name="urr-mock-plan",
            throttle=apigw.ThrottleSettings(rate_limit=50, burst_limit=100),
            quota=apigw.QuotaSettings(limit=100000, period=apigw.Period.MONTH),
        )
        plan.add_api_key(key)
        plan.add_api_stage(stage=api.deployment_stage)

        cdk.CfnOutput(self, "ApiBaseUrl", value=f"{api.url}api/v1",
                      description="Base URL; use in place of the real NSIF /api/v1. Send header x-api-key.")
        cdk.CfnOutput(self, "ApiKeyId", value=key.key_id,
                      description="Fetch the value: aws apigateway get-api-key --api-key <id> "
                                  "--include-value --profile aipoc-admin --region us-west-2")
        cdk.Tags.of(self).add("project", "urr-mock")
