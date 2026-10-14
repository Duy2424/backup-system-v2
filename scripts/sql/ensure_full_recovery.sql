-- Kiem tra / dat recovery model FULL (can de sao luu LOG va khoi phuc ve tung thoi diem).
-- Bien sqlcmd: DB
SET NOCOUNT ON;
IF DB_ID(N'$(DB)') IS NULL
    RAISERROR(N'Khong co CSDL $(DB)', 16, 1);
ELSE IF (SELECT recovery_model_desc FROM sys.databases WHERE name = N'$(DB)') <> N'FULL'
BEGIN
    ALTER DATABASE [$(DB)] SET RECOVERY FULL;
    PRINT N'Da chuyen $(DB) sang recovery model FULL - can 1 ban FULL moi truoc khi sao luu LOG';
END
ELSE
    PRINT N'$(DB) dang o recovery model FULL';
