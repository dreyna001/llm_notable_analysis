# FROM is org-specific: replace <image> and path with a Lambda Python 3.12 base you can pull.
# SAM parameter ImageUri must point at the same handler image after you build and push to ECR.
# Use AWS Lambda Python 3.12 base image
FROM <image>.dkr.ecr.us-east-1.amazonaws.com/ironbank/lambda.python:312

# Copy requirements file
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy function package and data files
COPY src/s3_notable_pipeline ${LAMBDA_TASK_ROOT}/s3_notable_pipeline
COPY deploy/servicenow ${LAMBDA_TASK_ROOT}/deploy/servicenow

# Set the CMD to your handler (could also be done as a parameter override)
CMD ["s3_notable_pipeline.lambda_handler.handler"]

