#!/bin/bash

CLUSTER_ALLOW_FLOCK=`cat << EOF
HOSTALLOW_WRITE_COLLECTOR = \$\(HOSTALLOW_WRITE\), \$\(FLOCK_FROM\)
HOSTALLOW_WRITE_STARTD = \$\(HOSTALLOW_WRITE\), \$\(FLOCK_FROM\)
HOSTALLOW_READ_COLLECTOR = \$\(HOSTALLOW_READ\), \$\(FLOCK_FROM\)
HOSTALLOW_READ_STARTD = \$\(HOSTALLOW_READ\), \$\(FLOCK_FROM\)
EOF
`

CLUSTER_FLOCK_COL_NEG=`cat << EOF
FLOCK_COLLECTOR_HOSTS = \$\(FLOCK_TO\)
FLOCK_NEGOTIATOR_HOSTS = \$\(FLOCK_TO\)
EOF
`

if [ "$1" == "master" ];
then
    echo "==> Check CONDOR_HOST"
    if [ "$CONDOR_HOST" == "ZOOKEEPER" ];
    then
        echo "==> CONDOR_HOST with Zookeeper"
        echo "==> Get Master IP"
        export CONDOR_HOST=$(hostname -i)
        echo "==> Set Master IP on Zookeeper"
        dodas_cache zookeeper CONDOR_HOST "$CONDOR_HOST"
        echo ""
    else
        echo "==> CONDOR_HOST with ENV"
    fi
    echo "==> Compile configuration file for master node with env vars"
    export NETWORK_INTERFACE=$(hostname -i)
    export NETWORK_INTERFACE_STRING="NETWORK_INTERFACE = $NETWORK_INTERFACE"
    export CONDOR_DAEMON_LIST="COLLECTOR, MASTER, NEGOTIATOR"
    export FLOCK_FROM="FLOCK_FROM = 192.168.0.*"
    export HOST_ALLOW_FLOCK="$CLUSTER_ALLOW_FLOCK"
    j2 /opt/dodas/htc_config/condor_config.template > /etc/condor/condor_config
    echo "==> Start condor"
    condor_master -f
elif [ "$1" == "wn" ];
then
    echo "==> Check CONDOR_HOST"
    if [ "$CONDOR_HOST" == "ZOOKEEPER" ];
    then
        echo "==> CONDOR_HOST with Zookeeper"
        echo "==> Get Master ip with Zookeeper"
        export CONDOR_HOST=$(dodas_cache --wait-for true zookeeper CONDOR_HOST)
        export CCB_ADDRESS="$CONDOR_HOST"
    else
        echo "==> CONDOR_HOST with ENV"
    fi
    echo "==> Compile configuration file for worker node with env vars"
    export CONDOR_DAEMON_LIST="MASTER, STARTD"
    export CCB_ADDRESS_STRING="CCB_ADDRESS = $CCB_ADDRESS"
    j2 /opt/dodas/htc_config/condor_config.template > /etc/condor/condor_config
    echo "==> Start condor"
    condor_master -f
    echo "==> Start service"
elif [ "$1" == "schedd" ];
then
    echo "==> Prepare schedd"
    adduser schedd
    passwd -d schedd
    ssh-keygen -q -t rsa -N '' -f /home/schedd/.ssh/id_rsa
    echo "==> Public schedd key"
    dodas_cache zookeeper SCHEDD_PUB_KEY "$(< /home/schedd/.ssh/id_rsa.pub)"
    dodas_cache zookeeper SCHEDD_PRIV_KEY "$(< /home/schedd/.ssh/id_rsa)"
    echo "==> Add authorized key"
    cat /home/schedd/.ssh/id_rsa.pub > /home/schedd/.ssh/authorized_keys
    chmod go-rw /home/schedd/.ssh/authorized_keys
    chown -R schedd:schedd /home/schedd/.ssh
    echo "==> Check CONDOR_HOST"
    if [ "$CONDOR_HOST" == "ZOOKEEPER" ];
    then
        echo "==> CONDOR_HOST with Zookeeper"
        echo "==> Get Master ip with Zookeeper"
        export CONDOR_HOST=$(dodas_cache --wait-for true zookeeper CONDOR_HOST)
    else
        echo "==> CONDOR_HOST with ENV"
    fi
    echo "==> Compile configuration file for sheduler node with env vars"
    export NETWORK_INTERFACE=$(hostname -i)
    export CONDOR_DAEMON_LIST="MASTER, SCHEDD"
    export NETWORK_INTERFACE_STRING="NETWORK_INTERFACE = $NETWORK_INTERFACE"
    j2 /opt/dodas/htc_config/condor_config.template > /etc/condor/condor_config
    echo "==> Public schedd host"
    dodas_cache zookeeper SCHEDD_HOST "$NETWORK_INTERFACE"
    echo ""
    echo "==> Start condor"
    condor_master
    echo "==> Start sshd on port $CONDOR_SCHEDD_SSH_PORT"
    exec /usr/sbin/sshd -E /var/log/sshd.log -g 30 -p $CONDOR_SCHEDD_SSH_PORT -D
elif [ "$1" == "flock" ];
then
    echo "==> Compile configuration file for flock cluster node with env vars"
    CLUSTER_CM=$(dodas_cache --wait-for true zookeeper CONDOR_HOST)
    export FLOCK_TO="FLOCK_TO = $CLUSTER_CM"
    export FLOCK_TO_COL_NEG="$CLUSTER_FLOCK_COL_NEG"
    # export NETWORK_INTERFACE=$(hostname -i)
    # export NETWORK_INTERFACE_STRING="NETWORK_INTERFACE = $NETWORK_INTERFACE"
    export CONDOR_DAEMON_LIST="MASTER, SCHEDD, COLLECTOR, NEGOTIATOR"
    j2 /opt/dodas/htc_config/condor_config.template > /etc/condor/condor_config
    echo "==> Start condor"
    condor_master
    echo "==> Start sshd on port 32042"
    exec /usr/sbin/sshd -E /var/log/sshd.log -g 30 -p 32042 -D
elif [ "$1" == "all" ];
then
    echo "==> Compile configuration file for sheduler node with env vars"
    j2 /opt/dodas/htc_config/condor_config.template > /etc/condor/condor_config
    echo "==> Start condor"
    condor_master -f
    echo "==> Start sshd on port $CONDOR_SCHEDD_SSH_PORT"
    exec /usr/sbin/sshd -E /var/log/sshd.log -g 30 -p $CONDOR_SCHEDD_SSH_PORT -D
elif [ "$1" == "sshonly" ];
then
    echo "==> Start sshd on port $CONDOR_SCHEDD_SSH_PORT"
    exec /usr/sbin/sshd -E /var/log/sshd.log -g 30 -p $CONDOR_SCHEDD_SSH_PORT -D
elif [ "$1" == "scheddtunnel" ];
then
    mkdir -p /opt/dodas/keys
    echo "==> Copy keys"
    dodas_cache --wait-for true zookeeper SCHEDD_PRIV_KEY > /opt/dodas/keys/id_rsa
    dodas_cache --wait-for true zookeeper SCHEDD_PUB_KEY > /opt/dodas/keys/id_rsa.pub
    chmod go-rw /opt/dodas/keys/id_rsa
    chmod go-w /opt/dodas/keys/id_rsa.pub
    echo "==> Check tunnel endpoints"
    if [ "$TUNNEL_FROM" == "UNDEFINED" ];
    then
        export TUNNEL_FROM="$CONDOR_SCHEDD_SSH_PORT"
    fi
    if [ "$TUNNEL_TO" == "UNDEFINED" ];
    then
        export TUNNEL_TO="$CONDOR_SCHEDD_SSH_PORT"
    fi
    export SCHEDD_HOST=$(dodas_cache --wait-for true zookeeper SCHEDD_HOST)
    echo "==> Start sshd tunnel"
    exec ssh -N -g -L $TUNNEL_FROM:$SCHEDD_HOST:$TUNNEL_TO -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no schedd@$SCHEDD_HOST -p $CONDOR_SCHEDD_SSH_PORT -i /opt/dodas/keys/id_rsa
else
    echo "[ERROR]==> You have to supply a role, like: 'master', 'wn', 'schedd' or 'all'..."
    exit 1
fi