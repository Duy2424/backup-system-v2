-- Sao luu NHAT KY GIAO DICH (moi 15 phut) - cho phep khoi phuc ve tung thoi diem (STOPAT).
-- Bien sqlcmd: DB, FILE
SET NOCOUNT ON;
BACKUP LOG [$(DB)] TO DISK = N'$(FILE)'
    WITH INIT, CHECKSUM, STATS = 10, NAME = N'$(DB) LOG';
RESTORE VERIFYONLY FROM DISK = N'$(FILE)' WITH CHECKSUM;
