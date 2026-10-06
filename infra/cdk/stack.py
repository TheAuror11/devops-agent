from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as ddb,
    aws_ec2 as ec2,
    aws_ecr_assets as assets,
    aws_ecs as ecs,
    aws_ecs_patterns as patterns,
    aws_iam as iam,
    aws_logs as logs,
    aws_sqs as sqs,
    aws_applicationautoscaling as appscaling,
)
from constructs import Construct


class DevOpsAgentStack(Stack):
    """Production control plane + investigation workers on ECS Fargate.

    Autoscales workers on SQS depth so a burst of incidents can run 100+
    concurrent investigations without blocking the API.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = ec2.Vpc(self, "Vpc", max_azs=2, nat_gateways=1)
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc, container_insights=True)

        table = ddb.Table(
            self,
            "Store",
            table_name="devops-agent-store",
            partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="sk", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
            encryption=ddb.TableEncryption.AWS_MANAGED,
        )

        dlq = sqs.Queue(
            self,
            "InvestigationDLQ",
            queue_name="devops-agent-investigations-dlq",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
        )
        queue = sqs.Queue(
            self,
            "InvestigationQueue",
            queue_name="devops-agent-investigations",
            visibility_timeout=Duration.minutes(15),
            retention_period=Duration.days(4),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=5, queue=dlq),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
        )

        image = ecs.ContainerImage.from_docker_image_asset(
            assets.DockerImageAsset(self, "Image", directory="../..", file="Dockerfile", target="api")
        )
        worker_image = ecs.ContainerImage.from_docker_image_asset(
            assets.DockerImageAsset(self, "WorkerImage", directory="../..", file="Dockerfile", target="worker")
        )

        env = {
            "APP_ENV": "prod",
            "STORE_BACKEND": "dynamodb",
            "QUEUE_BACKEND": "sqs",
            "DDB_TABLE_PREFIX": "devops-agent",
            "SQS_INVESTIGATION_QUEUE_URL": queue.queue_url,
            "SQS_DLQ_URL": dlq.queue_url,
            "SEED_DEMO_DATA": "false",
            "WORKER_CONCURRENCY": "4",
            "AWS_REGION": Stack.of(self).region,
        }

        api = patterns.ApplicationLoadBalancedFargateService(
            self,
            "Api",
            cluster=cluster,
            cpu=512,
            memory_limit_mib=1024,
            desired_count=2,
            public_load_balancer=True,
            task_image_options=patterns.ApplicationLoadBalancedTaskImageOptions(
                image=image,
                container_port=8080,
                environment=env,
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="api",
                    log_retention=logs.RetentionDays.ONE_MONTH,
                ),
            ),
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )
        api.target_group.configure_health_check(path="/healthz")
        api.service.auto_scale_task_count(min_capacity=2, max_capacity=8).scale_on_cpu_utilization(
            "ApiCpu", target_utilization_percent=60
        )

        worker_task = ecs.FargateTaskDefinition(self, "WorkerTask", cpu=1024, memory_limit_mib=2048)
        worker_task.add_container(
            "worker",
            image=worker_image,
            environment=env,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="worker", log_retention=logs.RetentionDays.ONE_MONTH),
        )
        worker_svc = ecs.FargateService(
            self,
            "Worker",
            cluster=cluster,
            task_definition=worker_task,
            desired_count=4,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )
        scaling = worker_svc.auto_scale_task_count(min_capacity=4, max_capacity=40)
        scaling.scale_on_metric(
            "SqsDepth",
            metric=queue.metric_approximate_number_of_messages_visible(),
            scaling_steps=[
                appscaling.ScalingInterval(upper=0, change=-1),
                appscaling.ScalingInterval(lower=1, change=+1),
                appscaling.ScalingInterval(lower=20, change=+4),
                appscaling.ScalingInterval(lower=80, change=+8),
            ],
            adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
            cooldown=Duration.seconds(60),
        )

        for principal in (api.task_definition.task_role, worker_task.task_role):
            table.grant_read_write_data(principal)
            queue.grant_send_messages(principal)
            queue.grant_consume_messages(principal)
            dlq.grant_consume_messages(principal)
            principal.add_to_policy(
                iam.PolicyStatement(
                    actions=[
                        "bedrock:InvokeModel",
                        "bedrock:InvokeModelWithResponseStream",
                    ],
                    resources=["*"],
                )
            )
            principal.add_to_policy(
                iam.PolicyStatement(
                    actions=[
                        "cloudwatch:GetMetricData",
                        "cloudwatch:DescribeAlarms",
                        "logs:FilterLogEvents",
                        "logs:DescribeLogGroups",
                        "xray:GetTraceSummaries",
                        "xray:BatchGetTraces",
                        "cloudtrail:LookupEvents",
                        "ecs:DescribeServices",
                        "ecs:DescribeTasks",
                        "lambda:GetFunction",
                        "lambda:ListFunctions",
                        "dynamodb:DescribeTable",
                        "config:GetResourceConfigHistory",
                        "sts:AssumeRole",
                    ],
                    resources=["*"],
                )
            )

        CfnOutput(self, "ApiUrl", value=api.load_balancer.load_balancer_dns_name)
        CfnOutput(self, "QueueUrl", value=queue.queue_url)
        CfnOutput(self, "TableName", value=table.table_name)
