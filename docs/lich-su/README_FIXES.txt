============================================================================
 HUONG DAN SUA & CHAY HE THONG BACKUP  (Do Hong Anh Duy - DACS)
============================================================================
Muc tieu: go het merge conflict de code CHAY DUOC (tung phan + toan bo),
dong thoi sua vai cho cho KHOP DUNG voi bao cao (vi bao cao da chot).

----------------------------------------------------------------------------
0. VAN DE GOC
----------------------------------------------------------------------------
Repo dang ket merge conflict chua giai quyet o 15 file (con dau
<<<<<<< HEAD / ======= / >>>>>>> c150db19...). Python/Flask se bao
SyntaxError ngay khi chay. Trong 2 nhanh:

  * HEAD          = DUNG theo bao cao  (dai 192.168.10.0/24,
                    endpoint /api/jobs/poll, xac thuc header X-Auth-Token)
  * c150db19...   = SAI so voi bao cao (dai 192.168.146.x,
                    /api/jobs/next, khong co token)

=> Quy tac xu ly: GIU HEAD, bo nhanh c150db19 o MOI file.

----------------------------------------------------------------------------
1. CAC FILE SACH CO SAN TRONG THU MUC NAY (chep de len repo)
----------------------------------------------------------------------------
6 file duoi day da go sach conflict (giu HEAD) + da sua cho khop bao cao.
Chep de (overwrite) vao dung vi tri trong repo:

  shared/config.py            -> giu HEAD; dai 192.168.10.x; doc AGENT_TOKEN;
                                 tu tim agent_config.txt o ca cau truc cu/moi.
  shared/database.py          -> SUA: status job mac dinh 'pending' (truoc la
                                 'queued'); get_next_job() loc WHERE status=
                                 'pending'; THEM bang `schedules` ngay trong
                                 init_db() (khop muc 3.1.7: "tao bang qua
                                 database.init_db()"). Tong cong 4 bang:
                                 users / backups / jobs / schedules.
  server/server.py            -> giu HEAD; decorator api_auth_required (kiem
                                 tra header X-Auth-Token); route /api/jobs/poll;
                                 DOI TEN route folder browser ->
                                 /api/folder-browser/quick va
                                 /api/folder-browser/list (khop Bang 2.3).
                                 Ten ham giu nguyen nen url_for trong template
                                 van chay.
  server/templates/dashboard.html
                              -> giu HEAD (Quick Picks ben trai, cay thu muc
                                 ben phai, progress bar AJAX 2 giay - dung nhu
                                 Hinh 3.7). SUA 2 cho:
                                 (a) coi job.status == "pending" la dang cho
                                     (truoc la "queued");
                                 (b) doc dung data.quick_picks tu agent (ban cu
                                     doc nham data.picks -> se loi khi mo
                                     bang chon thu muc).
  requirements.txt            -> PIN dung version theo muc 3.2.1:
                                 flask==3.0.0, werkzeug==3.0.1,
                                 requests==2.31.0, cryptography==42.0.5
  agent/agent_config.txt      -> giu HEAD; co dong SERVER_URL= va AGENT_TOKEN=.

----------------------------------------------------------------------------
2. CAC FILE CON LAI (go conflict tu dong bang script)
----------------------------------------------------------------------------
Nhung file sau chi can GIU HEAD (khong co thay doi logic), gom:

  .gitignore                       agent/agent.py
  README.md                        agent/system_state.py
  download_wheels.bat              agent/restore_logic.py   (chi 1 comment)
  install.bat                      agent/network_advanced.py
  agent/start_agent.bat            agent/sample_data/card_wifi.txt
  agent/sample_data/router.txt     agent/sample_data/sever.txt
  agent/backup_logic.py            (neu co dinh conflict)

Cach nhanh nhat (lam tren CHINH repo cua ban, an toan):

  B1. Sao luu repo truoc (commit/stash hoac copy ca thu muc).
  B2. Chep file  resolve_conflicts.py  (co trong thu muc nay) vao
      THU MUC GOC repo (cung cap voi server/ va agent/).
  B3. Chay:
          python resolve_conflicts.py
      Script tu quet, file nao con dau xung dot thi giu HEAD, bo nhanh kia.
      File nao da sach se duoc bo qua (khong dung toi).
  B4. Chep de 6 file sach o muc (1) vao repo (de co them cac sua khop bao cao).
  B5. Cai thu vien va chay:
          pip install -r requirements.txt

Vi sao giu HEAD cho cac file nay:
  - sample_data/*.txt : HEAD dung IP 192.168.10.20 / gateway 192.168.10.1 /
                        DNS 192.168.10.2 (khop Bang 3.5).
  - *.bat             : HEAD ghi Python 3.11 (khop muc 3.1.6 / 3.2.1).
  - agent.py          : HEAD goi /api/jobs/poll kem header X-Auth-Token,
                        co xu ly 401, bao completed truoc khi doi IP.
  - system_state.py   : HEAD nhan dien dai 192.168.10.x (Host-only).

----------------------------------------------------------------------------
3. CHAY THU (kiem tra tung phan + toan bo)
----------------------------------------------------------------------------
Tren may Server (Win Server 2016, 192.168.10.1):
  cd server
  python server.py
  -> mo trinh duyet http://192.168.10.1:5000  (admin/admin123)
  -> vao trang Admin, copy Token cua user1.

Tren may Agent (Win Server 2012 R2, 192.168.10.2):
  - Mo agent/agent_config.txt, dan token vao dong AGENT_TOKEN=
    (hoac dat bien moi truong BACKUP_AGENT_TOKEN).
  cd agent
  python agent.py
  -> agent poll moi 3 giay; tao job Backup tren web -> agent nhan & chay.

Kiem tra tung phan doc lap:
  - DB:        python -c "import sys; sys.path.insert(0,'shared'); import database; database.init_db(); print('DB OK - 4 bang')"
  - Server:    chay server.py, xem trang dashboard len duoc.
  - Agent:     chay agent.py, xem log poll va nhan job.
  - Backup:    tao job backup -> file .tar.gz ma hoa xuat hien trong storage/.
  - Restore:   tao job restore -> du lieu + cau hinh mang phuc hoi lai.

----------------------------------------------------------------------------
4. (TUY CHON) Firewall: doi sang export/import WFW cho KHOP CHU bao cao 2.3.3
----------------------------------------------------------------------------
Bao cao muc 2.3.3 viet: "export toan bo rule sang format WFW qua netsh
export... khi Restore, import lai bang netsh advfirewall import".

Code hien tai (agent/network_advanced.py) dang bat TUNG rule bang
PowerShell/netsh roi luu JSON, va phuc hoi tung rule bang
`netsh advfirewall firewall add rule`. Cach nay VAN CHAY DUNG, chi la khac
cau chu trong bao cao. Co 2 lua chon:

  (A) GIU NGUYEN cach per-rule. Khi hoi dong hoi, giai thich:
      "Em export/import theo tung rule de kiem soat & loc duoc rule trung,
       ket qua tuong duong import ca file WFW." -> hoan toan bao ve duoc.

  (B) DOI sang WFW cho khop tuyet doi. Lam nhu sau:

    -- Trong agent/network_advanced.py, them 2 ham (dat canh cac ham firewall):

        def export_firewall_wfw(out_path):
            """Export toan bo cau hinh firewall ra file .wfw"""
            if not config.IS_WINDOWS:
                return False
            # _run_cmd la helper chay lenh san co trong file nay
            _run_cmd('netsh advfirewall export "%s"' % out_path)
            return os.path.exists(out_path)

        def import_firewall_wfw(wfw_path):
            """Import (phuc hoi) cau hinh firewall tu file .wfw"""
            if not config.IS_WINDOWS or not os.path.exists(wfw_path):
                return False
            _run_cmd('netsh advfirewall import "%s"' % wfw_path)
            return True

    -- Bo (hoac de lai khong dung) cac ham bat/phuc hoi tung rule cu
       (get_firewall_rules / restore_firewall_rules / _get_firewall_rules_netsh)
       va bo khoa "firewall_rules" trong cac dict capture/restore/compare.

    -- Trong agent/backup_logic.py: o buoc chup firewall, export ra
       work_dir/firewall/firewall.wfw, roi them vao tar tai duong dan
       _firewall/firewall.wfw. Bo dong log lien quan firewall_rules.

    -- Trong agent/restore_logic.py: SAU khi goi restore_system_state(),
       kiem tra os.path.join(extract_dir, "_firewall", "firewall.wfw");
       neu ton tai thi goi import_firewall_wfw(...) (bao trong try/except).
       LUU Y: chuyen lenh shutil.rmtree(work_dir) xuong CUOI cung, sau khi
       da import xong (de file .wfw chua bi xoa truoc khi import).

  Luu y bao ve: import ca file WFW se GHI DE toan bo rule hien co (ke ca rule
  inbound/outbound he thong). Trong moi truong demo VM thi an toan; tren may
  that nen sao luu cau hinh firewall truoc.

  (Vi minh khong sua truc tiep 3 file agent nay - de tranh lam lech cac phan
   khac trong code ban da viet - phan (B) de ban tu ap dung neu muon. Neu giu
   (A) thi khong can dong toi.)

----------------------------------------------------------------------------
5. MAY DIEM LECH KHAC NEN BIET (de tra loi hoi dong)
----------------------------------------------------------------------------
- Bang 2.2 (HTTP methods) liet ke vai endpoint khong co trong code that
  (GET /api/backups, POST /api/jobs/create, PATCH, DELETE /api/users/{id}).
  Bang 2.3 moi la danh sach endpoint THUC. Neu bi hoi: noi Bang 2.2 la bang
  MINH HOA khai niem HTTP method (GET/POST/PUT/PATCH/DELETE), con Bang 2.3 la
  API thuc thi.
- get_next_job() lay job theo thu tu tao (hang doi chung), 1 agent xu ly tuan
  tu job cua ca 2 user - dung nhu mo ta muc 3.3.4. (Khong loc theo user o tang
  job; phan luu tru storage thi da loc theo user.)
- system_state.py co capture/restore Windows Defender - day la phan code lam
  THEM, khong nam trong 6 thanh phan mang chinh cua bao cao. De nguyen cung
  duoc; neu bi hoi "Defender o dau trong bao cao?" thi noi day la phan mo rong.

============================================================================
 TOM TAT: chay resolve_conflicts.py -> chep de 6 file sach -> pip install
 -> chay server roi agent. Phan WFW (muc 4) la tuy chon.
============================================================================

----------------------------------------------------------------------------
6. THU MUC test-scripts/  (script test restore) + PUSH GITHUB
----------------------------------------------------------------------------
Thu muc test-scripts/ trong bo nay chua 9 cap file doi_*/check_* de test
khoi phuc tung thanh phan (firewall, IPv4, IPv6, hosts, share, route,
port proxy, defender). Cach dung xem test-scripts/README_TEST.txt.

Dat ca thu muc test-scripts/ vao THU MUC GOC repo (ngang hang server/, agent/).

Sau khi da go conflict + chep de file sach xong, push len GitHub:

    git add .
    git commit -m "Fix merge conflicts, dong bo voi bao cao, them script test restore"
    git push

(Neu KHONG muon dua file phu vao repo GitHub, co the xoa truoc khi commit:
 resolve_conflicts.py  va  README_FIXES.txt  - day la file huong dan, khong
 thuoc he thong.)
============================================================================
