// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title FaceAnchor
/// @notice Tamper-evident anchor for face-match records. Stores the hash of a
///         canonical record payload together with the time it was submitted and
///         by whom. The payload itself stays off-chain; only its hash is anchored.
/// @dev No owner, no access control, no upgradeability. Anyone may anchor, and
///      no record can ever be overwritten or removed.
contract FaceAnchor {
    struct Record {
        uint256 timestamp;
        string uri;
        address submitter;
    }

    /// @notice Anchored records, keyed by the canonical record hash.
    mapping(bytes32 => Record) private records;

    /// @notice Emitted once per record hash, when it is first anchored.
    event Anchored(bytes32 indexed recordHash, address indexed submitter, uint256 timestamp, string uri);

    /// @notice Thrown when a record hash has already been anchored.
    /// @dev Re-anchoring would let a submitter reset the timestamp and defeat
    ///      the tamper-evidence the contract exists to provide.
    error RecordAlreadyAnchored(bytes32 recordHash);

    /// @notice Anchor a record hash on-chain, permanently and only once.
    /// @param recordHash SHA-256 of the canonical JSON record payload.
    /// @param uri Pointer to the off-chain payload this hash was computed from.
    function anchor(bytes32 recordHash, string calldata uri) external {
        if (records[recordHash].timestamp != 0) revert RecordAlreadyAnchored(recordHash);
        records[recordHash] = Record(block.timestamp, uri, msg.sender);
        emit Anchored(recordHash, msg.sender, block.timestamp, uri);
    }

    /// @notice Read back what was anchored for a record hash.
    /// @param recordHash The record hash to look up.
    /// @return exists True if this hash has been anchored.
    /// @return timestamp Block timestamp at which it was anchored, 0 if never.
    /// @return uri The pointer stored alongside it, empty if never anchored.
    /// @return submitter The address that anchored it, zero address if never.
    function verify(bytes32 recordHash) external view
        returns (bool exists, uint256 timestamp, string memory uri, address submitter)
    {
        Record storage r = records[recordHash];
        return (r.timestamp != 0, r.timestamp, r.uri, r.submitter);
    }
}
