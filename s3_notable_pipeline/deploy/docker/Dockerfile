# Production builds should override this with a customer-approved, digest-pinned mirror.
ARG LAMBDA_BASE_IMAGE=public.ecr.aws/lambda/python:3.12
FROM ${LAMBDA_BASE_IMAGE}

# Copy requirements file
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy function package and data files
COPY src/s3_notable_pipeline ${LAMBDA_TASK_ROOT}/s3_notable_pipeline
COPY deploy/servicenow ${LAMBDA_TASK_ROOT}/deploy/servicenow

# Set the CMD to your handler (could also be done as a parameter override)
CMD ["s3_notable_pipeline.lambda_handler.handler"]

