import socket


HOST = "127.0.0.1"
PORT = 5001
MAX_REQUEST_BYTES = 4096


def handle_client(connection, address):
    connection.settimeout(5)
    chunks = []
    size = 0

    try:
        while size <= MAX_REQUEST_BYTES:
            chunk = connection.recv(min(1024, MAX_REQUEST_BYTES + 1 - size))
            if not chunk:
                break
            newline = chunk.find(b"\n")
            if newline >= 0:
                chunks.append(chunk[:newline])
                size += newline
                break
            chunks.append(chunk)
            size += len(chunk)

        if size > MAX_REQUEST_BYTES:
            response = "Request is too large"
        else:
            try:
                order = b"".join(chunks).decode("utf-8").strip()
            except UnicodeDecodeError:
                response = "Request must be valid UTF-8"
            else:
                if not order:
                    response = "Request cannot be empty"
                else:
                    print(f"Client connected: {address}")
                    response = f"Order received by warehouse server: {order}"

        connection.sendall(response.encode("utf-8"))
    except socket.timeout:
        try:
            connection.sendall(b"Request timed out")
        except OSError as error:
            print(f"Could not report TCP timeout to client: {error}")
    except OSError as error:
        print(f"TCP client connection failed: {error}")


def start_server():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((HOST, PORT))
            server.listen(5)
        except OSError as error:
            print(
                f"Could not start the warehouse server on "
                f"{HOST}:{PORT}: {error}"
            )
            return False

        print("======================================")
        print("SMART WAREHOUSE TCP SERVER")
        print("======================================")
        print(f"Server listening on {HOST}:{PORT}")
        print("Waiting for client...")

        while True:
            try:
                connection, address = server.accept()
            except OSError as error:
                print(f"TCP server stopped accepting connections: {error}")
                return

            with connection:
                handle_client(connection, address)


if __name__ == "__main__":
    start_server()