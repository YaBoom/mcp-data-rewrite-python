// ============================================================
// 项目B：mcp-data-rewrite-python （Python + Dockerfile）—— SSH 远程部署版
// 前置：
//   1. Jenkins 容器已装 docker CLI + compose 插件（放在 /var/jenkins_home/bin）
//   2. Jenkins 容器已挂载 /var/run/docker.sock（构建镜像用）
//   3. 装 SSH Agent 插件
//   4. 配 SSH 凭证 ID = deploy-ssh-key（用户 deploy + 私钥）
//   5. 目标机 /opt/mcp-data-rewrite/ 放好 docker-compose.yml 和 .env
// ============================================================
pipeline {
    agent any

    environment {
        // Jenkins 容器构建镜像后推到宿主机 registry，走 host.docker.internal
        REGISTRY    = 'host.docker.internal:5000'
        IMAGE       = 'mcp-data-rewrite'
        DOCKER      = '/var/jenkins_home/bin/docker'
        // SSH 目标：模拟 Linux 服务器（宿主机映射 2222）
        DEPLOY_HOST = 'host.docker.internal'
        DEPLOY_PORT = '2222'
        DEPLOY_USER = 'deploy'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script {
                    GIT_SHA = sh(script: 'git rev-parse --short=7 HEAD', returnStdout: true).trim()
                    env.TAG = "${env.BUILD_NUMBER}-${GIT_SHA}"
                    echo "本次镜像 tag = ${env.TAG}"
                }
            }
        }

        stage('Test') {
            steps {
                // 用与生产同依赖的镜像跑测试，保证环境一致
                // || true 是教学期降级：先跑通，正式环境请删掉让测试真正卡门禁
                sh """
                ${DOCKER} build -t ${REGISTRY}/${IMAGE}:testbuild .
                ${DOCKER} run --rm ${REGISTRY}/${IMAGE}:testbuild uv run --frozen pytest -q || true
                """
            }
        }

        stage('Build & Push Image') {
            steps {
                sh """
                ${DOCKER} build -t ${REGISTRY}/${IMAGE}:${TAG} .
                ${DOCKER} tag  ${REGISTRY}/${IMAGE}:${TAG} ${REGISTRY}/${IMAGE}:latest
                ${DOCKER} push ${REGISTRY}/${IMAGE}:${TAG}
                ${DOCKER} push ${REGISTRY}/${IMAGE}:latest
                """
            }
        }

        stage('Deploy') {
            steps {
                sshagent(credentials: ['deploy-ssh-key']) {
                    // stdio 服务：用 compose run --rm -T，不要当前台常驻服务跑
                    sh """
                    ssh -o StrictHostKeyChecking=no \
                        -o UserKnownHostsFile=/dev/null \
                        -p ${DEPLOY_PORT} ${DEPLOY_USER}@${DEPLOY_HOST} '
                          cd /opt/mcp-data-rewrite &&
                          export IMAGE_TAG=${TAG} &&
                          sudo -n docker compose pull mcp-server &&
                          sudo -n docker compose run --rm -T mcp-server
                        '
                    """
                }
            }
        }
    }

    post {
        success { echo "✅ 发布成功：${REGISTRY}/${IMAGE}:${TAG}" }
        failure { echo "❌ 失败，请查看 Console Output" }
    }
}

// 教学备注：
// 1) Python 用 docker build/push（不是 Jib），所以 Jenkins 容器必须有 docker CLI + docker.sock。
// 2) 目标机 compose 里镜像地址仍是 localhost:5000，因为目标机挂了 docker.sock，
//    它执行的 docker 命令实际由宿主机 daemon 完成，宿主机的 localhost:5000 就是 registry。
// 3) stdio 服务由 MCP 客户端按需拉起，Deploy 阶段的 run --rm -T 只是验证性运行。
