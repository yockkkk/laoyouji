import json
import uuid
import datetime
import paramiko

def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect('159.75.94.149', port=22, username='xiaoyuyu', password='Wsxy8829', timeout=15)

    trip_id = f"trip_cs_{uuid.uuid4().hex[:8]}"
    elder_id = "442b298a-0ebf-4e07-864d-696704a0631c"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    route_data = {
        "ok": True,
        "origin": "家（长沙市开福区华夏路社区）",
        "destination": "中南大学湘雅医院",
        "city": "长沙",
        "mode": "步行",
        "duration": "约8分钟",
        "distance_km": 0.48,
        "bds_satellite_count": 18,
        "bds_accuracy_m": 0.35,
        "barrier_free_score": 0.98,
        "points": [
            {"location": "家（长沙市开福区华夏路社区）", "name": "家（华夏路社区）", "lng": 112.9862, "lat": 28.2154},
            {"location": "华夏路林荫街心花园", "name": "街心花园休息长椅", "lng": 112.9865, "lat": 28.2148},
            {"location": "湘雅路有声安全斑马线", "name": "湘雅路有声安全斑马线", "lng": 112.9868, "lat": 28.2143},
            {"location": "中南大学湘雅医院", "name": "中南大学湘雅医院（湘雅路院区）", "lng": 112.9870, "lat": 28.2140}
        ],
        "polyline": [
            {"lng": 112.9862, "lat": 28.2154},
            {"lng": 112.9863, "lat": 28.2151},
            {"lng": 112.9865, "lat": 28.2148},
            {"lng": 112.9867, "lat": 28.2145},
            {"lng": 112.9868, "lat": 28.2143},
            {"lng": 112.9870, "lat": 28.2140}
        ],
        "steps": [
            {
                "title": "第 1 步：华夏路社区南门无障碍出口",
                "landmark": "华夏路社区便民服务亭",
                "icon": "🏡",
                "action_desc": "出小区沿华夏路适老防滑步道往南前行 150 米，途经街心花园休息长椅。",
                "accessible_features": ["无台阶", "全程平缓缓坡 (<2%)", "林荫遮阳步道"],
                "voice_hint": "张阿姨，顺着咱们小区门口平平的防滑步道慢慢走，路边有长椅可以歇歇脚。"
            },
            {
                "title": "第 2 步：湘雅路口有声安全斑马线",
                "landmark": "湘雅路口有声红绿灯",
                "icon": "🚦",
                "action_desc": "沿绿荫道慢行至湘雅路路口，过配备清脆语音提示的有声斑马线（绿灯时长 45 秒）。",
                "accessible_features": ["无台阶", "人车分流安全岛", "声响红绿灯指引 (45秒)"],
                "voice_hint": "张阿姨，经过路口有清脆的提示音，绿灯时间很长，慢慢过，不用着急。"
            },
            {
                "title": "第 3 步：中南大学湘雅医院门诊大楼 1 号无障碍坡道",
                "landmark": "中南大学湘雅医院门诊大楼",
                "icon": "🏥",
                "action_desc": "抵达湘雅医院门诊大楼，顺着左侧平缓无障碍专用坡道进入大厅，直通骨科与挂号处。",
                "accessible_features": ["无台阶", "防滑无障碍专用坡道", "无障碍直梯", "导医志愿者引导"],
                "voice_hint": "到达湘雅医院啦！走左边平缓坡道进门就是导医台，骨科在二楼。"
            }
        ]
    }

    trip_record = {
        "id": trip_id,
        "elder_id": elder_id,
        "origin": "家（长沙市开福区华夏路社区）",
        "destination": "中南大学湘雅医院",
        "purpose": "前往中南大学湘雅医院看门诊",
        "status": "ongoing",
        "route": route_data,
        "started_at": now_iso,
        "created_at": now_iso
    }

    trip_json_str = json.dumps(trip_record, ensure_ascii=False)
    # Save script to remote tmp sql file
    sftp = ssh.open_sftp()
    sql_content = f"""
USE laoyouji;
UPDATE laoyouji_records SET data = JSON_SET(data, '$.city', '长沙') WHERE table_name = 'users' AND id = '{elder_id}';
DELETE FROM laoyouji_records WHERE table_name = 'trips';
INSERT INTO laoyouji_records (table_name, id, data, created_at) VALUES ('trips', '{trip_id}', '{trip_json_str}', NOW(6));
"""
    with sftp.file('/tmp/update_changsha.sql', 'w') as f:
        f.write(sql_content.encode('utf-8'))
    sftp.close()

    cmd = "mysql --default-character-set=utf8mb4 -u xiaoyuyu -p'Wsxy8829' < /tmp/update_changsha.sql"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    print("SQL OUTPUT:", out)
    print("SQL ERR:", err)

    # Verification query
    check_sql = "USE laoyouji; SELECT id, JSON_EXTRACT(data, '$.city') FROM laoyouji_records WHERE table_name='users'; SELECT id, JSON_EXTRACT(data, '$.destination') FROM laoyouji_records WHERE table_name='trips';"
    stdin, stdout, stderr = ssh.exec_command(f"mysql --default-character-set=utf8mb4 -u xiaoyuyu -p'Wsxy8829' -e \"{check_sql}\"")
    print("VERIFY:\n", stdout.read().decode('utf-8', errors='replace'))

    ssh.close()
    print("Database updated to Changsha successfully!")

if __name__ == '__main__':
    main()
